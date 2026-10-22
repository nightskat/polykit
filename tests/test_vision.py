"""Comprehensive unit tests for bin/lib/vision.py.

Kiểm tra:
1. Cổng PII / sensitive:
   - Dữ liệu sensitive hoặc không tuyên bố synthetic rõ bị blocked mặc định.
   - Spy chứng minh: stat, open, exists, subprocess tuyệt đối KHÔNG được gọi khi bị chặn ở gate.
   - Cờ --allow-sensitive-vision một mình không đủ.
   - Chuỗi string bất kỳ không được nhận làm consent (bị từ chối dứt khoát).
   - Vì chưa có UI xác nhận Tuan đáng tin, sensitive luôn blocked fail-closed.
   - Confirmation không kế thừa qua retry hay failover; không tái sử dụng khi consumed.
   - Confirmation phải khớp exact files, model, provider.
2. Synthetic explicit & adapter verification:
   - API public không được tự chứng nhận adapter (xoá verified_adapters param).
   - Adapter rỗng ("" / whitespace / None) bị blocked fail-closed trước bất kỳ file I/O.
   - Chỉ so khớp với hằng frozen VERIFIED_VISION_ADAPTERS (hiện rỗng).
   - Test giả override bị loại bỏ; adapter unverified luôn bị blocked.
   - Trong môi trường unit test isolated, cho phép monkeypatch test-only registry.
3. Path security & Format validation:
   - Chỉ cho phép sau khi qua gate với is_synthetic=True và verified adapter.
   - Path thường trong workspace hợp lệ.
   - Symlink bị chặn (VisionSecurityError).
   - Path outside allowed workspace bị chặn (VisionSecurityError).
   - Path có khoảng trắng được xử lý đúng nguyên vẹn.
   - File thiếu, file là thư mục, file rỗng 0-byte bị từ chối (VisionFormatError).
   - Dung lượng vượt trần bị từ chối (VisionQuotaError).
4. MIME signature (magic bytes):
   - PNG magic signature b'\\x89PNG\\r\\n\\x1a\\n'.
   - JPEG magic signature b'\\xff\\xd8\\xff'.
   - PDF magic signature b'%PDF'.
   - Suffix .png nhưng nội dung text/rác -> VisionFormatError.
   - Suffix .pdf nhưng thiếu magic %PDF -> VisionFormatError.
   - Mismatch giữa suffix và MIME magic -> VisionFormatError.
5. DeepSeek PDF conversion:
   - Public wrapper convert_pdf_to_images bị blocked fail-closed trước bất kỳ I/O,
     không nhận pdftoppm_bin arbitrary để bypass.
   - Internal helper _convert_pdf_to_images:
     * Subprocess argv list (không shell=True), timeout rõ ràng.
     * Tách trang full resolution, không contact sheet.
     * Thứ tự trang số tự nhiên đúng (1, 2, ..., 10), không bị xếp theo bảng chữ cái.
     * Thiếu binary pdftoppm bị blocked.
     * Converter failure (nonzero returncode, timeout, output rỗng) được xử lý fail-closed.
6. High-level prepare_vision_input:
   - Public prepare_vision_input bị fail-closed khi adapter rỗng hoặc unverified.
   - Không nhận pdftoppm_bin arbitrary hoặc verified_adapters parameter.
   - Sensitive data bị blocked trước khi mở file hay chuyển đổi.
   - Chuyển đổi PDF hợp lệ qua helper nội bộ sau khi vượt gate trong test.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bin.lib.vision import (
    DEFAULT_MAX_FILE_BYTES,
    EXPECTED_MANIFEST_GENERATOR,
    EXPECTED_MANIFEST_SCHEMA_VERSION,
    JPEG_MAGIC,
    PDF_MAGIC,
    PNG_MAGIC,
    TRUSTED_MODEL_CAPABILITIES,
    VERIFIED_VISION_ADAPTERS,
    SingleTurnConfirmation,
    VisionAttachment,
    VisionBlockedError,
    VisionConversionError,
    VisionFormatError,
    VisionQuotaError,
    VisionSecurityError,
    _convert_pdf_to_images,
    check_vision_gate,
    convert_pdf_to_images,
    detect_mime_from_magic_bytes,
    get_model_capabilities,
    prepare_vision_input,
    validate_file_format,
    validate_synthetic_gate,
    verify_adapter,
)


# ===========================================================================
# Fixtures & Helpers
# ===========================================================================

TEST_ADAPTER_NAME = "test_verified_adapter"

# Payload cố định => hash fixture deterministic, KHÔNG nhận file bất kỳ.
FIXTURE_PNG_PAYLOAD = PNG_MAGIC + b"polykit-synthetic-vision-fixture-png"
FIXTURE_PDF_PAYLOAD = PDF_MAGIC + b"-1.7\npolykit-synthetic-vision-fixture-pdf\n"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_synthetic_repo(root: Path) -> dict:
    """Dựng cây repo giả tối thiểu: bench/vision/synthetic + manifest + registry khớp hash."""
    synth = root / "bench" / "vision" / "synthetic"
    synth.mkdir(parents=True)

    specs = {
        "fixture_page.png": ("PNG", FIXTURE_PNG_PAYLOAD),
        "fixture_doc.pdf": ("PDF", FIXTURE_PDF_PAYLOAD),
    }
    registry: dict[str, dict] = {}
    entries: list[dict] = []

    for name, (fmt, payload) in specs.items():
        (synth / name).write_bytes(payload)
        rel_path = f"bench/vision/synthetic/{name}"
        registry[name] = {
            "sha256": sha256_hex(payload),
            "bytes": len(payload),
            "format": fmt,
            "rel_path": rel_path,
        }
        entries.append(
            {
                "path": name,
                "rel_path": rel_path,
                "format": fmt,
                "bytes": len(payload),
                "sha256": sha256_hex(payload),
            }
        )

    manifest = {
        "schema_version": EXPECTED_MANIFEST_SCHEMA_VERSION,
        "generator": EXPECTED_MANIFEST_GENERATOR,
        "files": entries,
    }
    (synth / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "root": root,
        "synth": synth,
        "registry": registry,
        "manifest": manifest,
        "png": synth / "fixture_page.png",
        "pdf": synth / "fixture_doc.pdf",
    }


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create isolated workspace root."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def test_adapter(monkeypatch: pytest.MonkeyPatch) -> str:
    """Provide monkeypatched frozen registry for isolated test-only execution."""
    monkeypatch.setattr(
        "bin.lib.vision.VERIFIED_VISION_ADAPTERS",
        frozenset({TEST_ADAPTER_NAME}),
    )
    return TEST_ADAPTER_NAME


@pytest.fixture
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Repo root + registry tin cậy do test dựng, monkeypatch thẳng constant module.

    Hash sinh từ payload cố định nên deterministic; file lạ không tự động hợp lệ.
    """
    root = (tmp_path / "repo_root").resolve()
    root.mkdir()
    repo = build_synthetic_repo(root)
    monkeypatch.setattr("bin.lib.vision.REAL_REPO_ROOT", root)
    monkeypatch.setattr("bin.lib.vision.TRUSTED_SYNTHETIC_REGISTRY", repo["registry"])
    return repo


def create_sample_png(path: Path, content: bytes = b"sample image data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(PNG_MAGIC + content)
    return path


def create_sample_jpeg(path: Path, content: bytes = b"sample jpeg data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(JPEG_MAGIC + content)
    return path


def create_sample_pdf(path: Path, content: bytes = b"-1.7\nsample pdf") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(PDF_MAGIC + content)
    return path


# ===========================================================================
# 1. CỔNG SENSITIVE / PII GATE (SPY TRƯỚC STAT/OPEN/SUBPROCESS)
# ===========================================================================

class TestSensitiveVisionGateSpy:
    """Spy tests ensuring NO file I/O or subprocess occurs on sensitive data."""

    def test_sensitive_default_blocked_without_file_io(self, workspace: Path):
        """Mặc định khi không tuyên bố is_synthetic=True thì bị chặn ngay tại gate,
        không gọi bất kỳ stat, open hay subprocess nào."""
        sensitive_file = workspace / "bank_scan_with_pii.png"
        create_sample_png(sensitive_file)

        with patch("os.stat") as mock_os_stat, \
             patch("builtins.open") as mock_open, \
             patch("subprocess.run") as mock_subprocess:

            with pytest.raises(VisionBlockedError, match="blocked by default"):
                check_vision_gate(
                    files=[sensitive_file],
                    model="deepseek-v4.1-flash",
                    is_synthetic=False,
                    workspace_root=workspace,
                )

            # Khẳng định chốt chặn bảo vệ: Không có bất kỳ I/O nào
            mock_os_stat.assert_not_called()
            mock_open.assert_not_called()
            mock_subprocess.assert_not_called()

    def test_allow_sensitive_alone_not_sufficient(self, workspace: Path):
        """Cờ --allow-sensitive-vision luôn bị chặn fail-closed, kể cả khi thiếu confirmation."""
        sensitive_file = workspace / "id_card.png"
        create_sample_png(sensitive_file)

        with patch("builtins.open") as mock_open, \
             patch("subprocess.run") as mock_subprocess:

            with pytest.raises(VisionBlockedError, match="--allow-sensitive-vision is blocked fail-closed"):
                check_vision_gate(
                    files=[sensitive_file],
                    model="deepseek-v4.1-flash",
                    is_synthetic=False,
                    allow_sensitive=True,
                    confirmation=None,
                    workspace_root=workspace,
                )

            mock_open.assert_not_called()
            mock_subprocess.assert_not_called()

    def test_sensitive_flags_block_even_without_files(self):
        """Cờ sensitive/confirmation luôn blocked fail-closed ngay cả khi không có file nào."""
        with patch("builtins.open") as mock_open, \
             patch("subprocess.run") as mock_subprocess:

            with pytest.raises(VisionBlockedError, match="--allow-sensitive-vision is blocked fail-closed"):
                check_vision_gate(files=[], model="deepseek-v4.1-flash", allow_sensitive=True)

            with pytest.raises(VisionBlockedError, match="(--allow-sensitive-vision is blocked fail-closed|Sensitive vision confirmation is blocked)"):
                check_vision_gate(files=[], model="deepseek-v4.1-flash", confirmation="anything")

            mock_open.assert_not_called()
            mock_subprocess.assert_not_called()

    def test_arbitrary_string_consent_rejected(self, workspace: Path):
        """KHÔNG nhận chuỗi string bất kỳ làm consent (ví dụ 'yes', 'Tuan', 'confirm')."""
        sensitive_file = workspace / "passport.jpg"
        create_sample_jpeg(sensitive_file)

        for fake_string in ["yes", "confirm", "I agree", "Tuan approved", "true", "1"]:
            with patch("builtins.open") as mock_open:
                with pytest.raises(VisionBlockedError, match="(--allow-sensitive-vision is blocked fail-closed|Sensitive vision confirmation is blocked)"):
                    check_vision_gate(
                        files=[sensitive_file],
                        model="deepseek-v4.1-flash",
                        is_synthetic=False,
                        allow_sensitive=True,
                        confirmation=fake_string,
                        workspace_root=workspace,
                    )
                mock_open.assert_not_called()

    def test_untrusted_ui_confirmation_blocked(self, workspace: Path):
        """Vì chưa có UI xác nhận Tuan đáng tin, sensitive luôn blocked fail-closed."""
        sensitive_file = workspace / "tax_report.pdf"
        create_sample_pdf(sensitive_file)

        conf = SingleTurnConfirmation(
            token="nonce-1234",
            exact_files=(str(sensitive_file),),
            exact_model="deepseek-v4.1-flash",
            exact_provider="opencode-go",
            is_trusted_ui=False,  # Chưa có UI đáng tin
        )

        with patch("builtins.open") as mock_open:
            with pytest.raises(VisionBlockedError, match="(--allow-sensitive-vision is blocked fail-closed|Sensitive vision confirmation is blocked)"):
                check_vision_gate(
                    files=[sensitive_file],
                    model="deepseek-v4.1-flash",
                    provider="opencode-go",
                    is_synthetic=False,
                    allow_sensitive=True,
                    confirmation=conf,
                    workspace_root=workspace,
                )
            mock_open.assert_not_called()

    def test_confirmation_cannot_inherit_across_retry_or_failover(self, workspace: Path):
        """Confirmation không được kế thừa qua retry hoặc failover: mọi confirmation đều bị chặn."""
        sensitive_file = workspace / "contract.png"
        create_sample_png(sensitive_file)

        conf = SingleTurnConfirmation(
            token="nonce-1234",
            exact_files=(str(sensitive_file),),
            exact_model="deepseek-v4.1-flash",
            exact_provider="opencode-go",
            is_trusted_ui=True,
        )

        # Retry check
        with pytest.raises(VisionBlockedError, match="(--allow-sensitive-vision is blocked fail-closed|Sensitive vision confirmation is blocked)"):
            check_vision_gate(
                files=[sensitive_file],
                model="deepseek-v4.1-flash",
                provider="opencode-go",
                is_synthetic=False,
                allow_sensitive=True,
                confirmation=conf,
                is_retry=True,
                workspace_root=workspace,
            )

        # Failover check
        with pytest.raises(VisionBlockedError, match="(--allow-sensitive-vision is blocked fail-closed|Sensitive vision confirmation is blocked)"):
            check_vision_gate(
                files=[sensitive_file],
                model="deepseek-v4.1-flash",
                provider="opencode-go",
                is_synthetic=False,
                allow_sensitive=True,
                confirmation=conf,
                is_failover=True,
                workspace_root=workspace,
            )

    def test_confirmation_mismatched_scope_rejected(self, workspace: Path):
        """Confirmation lệch files/model/provider vẫn bị chặn (mọi confirmation bị từ chối)."""
        f1 = workspace / "page1.png"
        f2 = workspace / "page2.png"
        create_sample_png(f1)
        create_sample_png(f2)

        conf = SingleTurnConfirmation(
            token="nonce-abc",
            exact_files=(str(f1),),
            exact_model="deepseek-v4.1-flash",
            exact_provider="opencode-go",
            is_trusted_ui=True,
        )

        # Mismatch files
        with pytest.raises(VisionBlockedError, match="(--allow-sensitive-vision is blocked fail-closed|Sensitive vision confirmation is blocked)"):
            check_vision_gate(
                files=[f1, f2],
                model="deepseek-v4.1-flash",
                provider="opencode-go",
                is_synthetic=False,
                allow_sensitive=True,
                confirmation=conf,
                workspace_root=workspace,
            )

        # Mismatch model
        with pytest.raises(VisionBlockedError, match="(--allow-sensitive-vision is blocked fail-closed|Sensitive vision confirmation is blocked)"):
            check_vision_gate(
                files=[f1],
                model="glm-5.3-flash",
                provider="opencode-go",
                is_synthetic=False,
                allow_sensitive=True,
                confirmation=conf,
                workspace_root=workspace,
            )

        # Mismatch provider
        with pytest.raises(VisionBlockedError, match="(--allow-sensitive-vision is blocked fail-closed|Sensitive vision confirmation is blocked)"):
            check_vision_gate(
                files=[f1],
                model="deepseek-v4.1-flash",
                provider="other-provider",
                is_synthetic=False,
                allow_sensitive=True,
                confirmation=conf,
                workspace_root=workspace,
            )

    def test_confirmation_consumed_cannot_be_reused(self, workspace: Path):
        """Confirmation đã consumed không được tái sử dụng."""
        f1 = workspace / "page1.png"
        create_sample_png(f1)

        consumed_conf = SingleTurnConfirmation(
            token="nonce-xyz",
            exact_files=(str(f1),),
            exact_model="deepseek-v4.1-flash",
            exact_provider="opencode-go",
            is_trusted_ui=True,
            consumed=True,
        )

        with pytest.raises(VisionBlockedError, match="(--allow-sensitive-vision is blocked fail-closed|Sensitive vision confirmation is blocked)"):
            check_vision_gate(
                files=[f1],
                model="deepseek-v4.1-flash",
                provider="opencode-go",
                is_synthetic=False,
                allow_sensitive=True,
                confirmation=consumed_conf,
                workspace_root=workspace,
            )

    def test_sensitive_always_blocked_fail_closed_even_with_confirmation(self, workspace: Path):
        """Ngay cả khi confirmation có is_trusted_ui=True, sensitive vẫn bị chặn fail-closed
        trước bất kỳ file stat hay open nào do chưa có UI xác nhận."""
        f1 = workspace / "secret.png"
        create_sample_png(f1)

        trusted_conf = SingleTurnConfirmation(
            token="nonce-trusted",
            exact_files=(str(f1),),
            exact_model="deepseek-v4.1-flash",
            exact_provider="opencode-go",
            is_trusted_ui=True,
        )

        with patch("builtins.open") as mock_open, \
             patch("os.stat") as mock_stat:
            with pytest.raises(VisionBlockedError, match="--allow-sensitive-vision is blocked fail-closed"):
                check_vision_gate(
                    files=[f1],
                    model="deepseek-v4.1-flash",
                    provider="opencode-go",
                    adapter="test_adapter",
                    is_synthetic=False,
                    allow_sensitive=True,
                    confirmation=trusted_conf,
                    workspace_root=workspace,
                )
            mock_open.assert_not_called()
            mock_stat.assert_not_called()


# ===========================================================================
# 2. SYNTHETIC EXPLICIT & PATH SECURITY (TEST-ONLY ADAPTER)
# ===========================================================================

class TestSyntheticPathSecurity:
    """Cổng synthetic chỉ mở cho file trong bench/vision/synthetic dưới REAL_REPO_ROOT,
    khớp manifest + registry; mọi path lạ/symlink/traversal bị chặn."""

    def test_valid_synthetic_regular_file(self, synthetic_repo: dict, test_adapter: str):
        """File fixture khớp manifest + registry đi qua cổng."""
        res = check_vision_gate(
            files=[synthetic_repo["png"]],
            model="deepseek-v4.1-flash",
            adapter=test_adapter,
            is_synthetic=True,
        )
        assert len(res) == 1
        assert res[0].mime_type == "image/png"
        assert res[0].is_synthetic is True

    def test_arbitrary_workspace_file_blocked(self, workspace: Path, test_adapter: str):
        """File synthetic tự tạo ngoài bench/vision/synthetic bị chặn (VisionSecurityError)."""
        img = create_sample_png(workspace / "test.png")
        with pytest.raises(VisionSecurityError, match="outside fixed synthetic directory"):
            check_vision_gate(
                files=[img],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
            )

    def test_symlink_blocked(self, synthetic_repo: dict, test_adapter: str):
        """Symlink (kể cả trỏ tới file hợp lệ trong synthetic dir) bị chặn tuyệt đối."""
        link_img = synthetic_repo["synth"] / "symlink_to_real.png"
        try:
            link_img.symlink_to(synthetic_repo["png"])
        except OSError:
            pytest.skip("Filesystem does not support symlinks")

        with pytest.raises(VisionSecurityError, match="Symlink detected"):
            check_vision_gate(
                files=[link_img],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
            )

    def test_path_outside_synthetic_dir_blocked(self, synthetic_repo: dict, tmp_path: Path, test_adapter: str):
        """Path ngoài synthetic dir (kể cả trong repo) bị chặn (VisionSecurityError)."""
        outside_file = create_sample_png(synthetic_repo["root"] / "outside" / "external.png")

        with pytest.raises(VisionSecurityError, match="outside fixed synthetic directory"):
            check_vision_gate(
                files=[outside_file],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
            )

    def test_path_traversal_blocked(self, synthetic_repo: dict, test_adapter: str):
        """Thử dùng traversal ../.. thoát khỏi synthetic dir."""
        traversal_path = synthetic_repo["synth"] / ".." / "escape.png"
        with pytest.raises(VisionSecurityError, match="Path traversal"):
            check_vision_gate(
                files=[traversal_path],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
            )

    def test_path_with_whitespace_supported(self, workspace: Path):
        """validate_file_format độc lập xử lý path có khoảng trắng nguyên vẹn (không tách từ)."""
        spaced_file = create_sample_png(workspace / "my synthetic documents" / "diagram draft v1.png")

        att = validate_file_format(spaced_file, workspace)
        assert att.mime_type == "image/png"
        assert att.path == spaced_file.resolve()
        assert "diagram draft v1.png" in str(att.path)

    def test_missing_file_rejected(self, synthetic_repo: dict, test_adapter: str):
        """File không tồn tại trong synthetic dir bị từ chối (VisionFormatError)."""
        missing = synthetic_repo["synth"] / "non_existent.png"
        with pytest.raises(VisionFormatError, match="Synthetic file not found"):
            check_vision_gate(
                files=[missing],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
            )

    def test_directory_rejected(self, synthetic_repo: dict, test_adapter: str):
        """Thư mục truyền vào làm attachment bị từ chối (VisionFormatError)."""
        d = synthetic_repo["synth"] / "some_dir.png"
        d.mkdir()
        with pytest.raises(VisionFormatError, match="Not a regular file"):
            check_vision_gate(
                files=[d],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
            )

    def test_empty_file_rejected(self, synthetic_repo: dict, test_adapter: str):
        """File 0 bytes bị từ chối (VisionFormatError)."""
        empty_file = synthetic_repo["synth"] / "empty.png"
        empty_file.touch()
        with pytest.raises(VisionFormatError, match="Synthetic file is empty"):
            check_vision_gate(
                files=[empty_file],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
            )

    def test_quota_size_limit_exceeded(self, synthetic_repo: dict, test_adapter: str):
        """File vượt hạn dung lượng bị chặn (VisionQuotaError)."""
        with pytest.raises(VisionQuotaError, match="exceeds max size"):
            check_vision_gate(
                files=[synthetic_repo["png"]],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
                max_bytes=10,
            )

    def test_registry_file_not_declared_in_manifest_blocked(
        self, synthetic_repo: dict, test_adapter: str, monkeypatch: pytest.MonkeyPatch
    ):
        """File có trong registry nhưng manifest không khai báo vẫn bị chặn (danh sách đóng)."""
        orphan = "orphan_page.png"
        payload = PNG_MAGIC + b"orphan page outside manifest"
        (synthetic_repo["synth"] / orphan).write_bytes(payload)

        registry = dict(synthetic_repo["registry"])
        registry[orphan] = {
            "sha256": sha256_hex(payload),
            "bytes": len(payload),
            "format": "PNG",
            "rel_path": f"bench/vision/synthetic/{orphan}",
        }
        monkeypatch.setattr("bin.lib.vision.TRUSTED_SYNTHETIC_REGISTRY", registry)

        with pytest.raises(VisionBlockedError, match="not declared in the synthetic manifest"):
            check_vision_gate(
                files=[synthetic_repo["synth"] / orphan],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
            )


# ===========================================================================
# 3. MIME SIGNATURE (MAGIC BYTES) & FORMAT VALIDATION
# ===========================================================================

class TestMimeSignatures:
    """Kiểm tra nhận diện signature MIME thật, không chỉ dựa vào đuôi file."""

    def test_detect_mime_magic_helpers(self):
        assert detect_mime_from_magic_bytes(PNG_MAGIC + b"extra") == "image/png"
        assert detect_mime_from_magic_bytes(JPEG_MAGIC + b"extra") == "image/jpeg"
        assert detect_mime_from_magic_bytes(PDF_MAGIC + b"-1.5") == "application/pdf"
        assert detect_mime_from_magic_bytes(b"PLAIN TEXT") is None

    def test_validate_file_format_direct(self, workspace: Path):
        """Kiểm tra trực tiếp hàm validate_file_format độc lập."""
        img = create_sample_png(workspace / "direct.png")
        att = validate_file_format(img, workspace)
        assert att.mime_type == "image/png"
        assert att.is_image is True
        assert att.is_pdf is False

    def test_validate_file_format_png_suffix_with_fake_content_rejected(self, workspace: Path):
        """Đuôi .png nhưng nội dung là text rác: validate_file_format từ chối theo magic bytes."""
        fake_png = workspace / "fake.png"
        fake_png.write_text("This is not a real PNG file, just text")

        with pytest.raises(VisionFormatError, match="magic bytes do not match"):
            validate_file_format(fake_png, workspace)

    def test_validate_file_format_pdf_suffix_without_magic_rejected(self, workspace: Path):
        """Đuôi .pdf nhưng thiếu magic %PDF: validate_file_format từ chối."""
        fake_pdf = workspace / "fake.pdf"
        fake_pdf.write_bytes(b"NOT_A_PDF_CONTENT_HEADER")

        with pytest.raises(VisionFormatError, match="magic bytes do not match"):
            validate_file_format(fake_pdf, workspace)

    def test_validate_file_format_suffix_mime_mismatch_rejected(self, workspace: Path):
        """Nội dung là PNG magic nhưng đuôi lại đặt là .jpg."""
        mismatch_file = workspace / "wrong_extension.jpg"
        mismatch_file.write_bytes(PNG_MAGIC + b"some png content")

        with pytest.raises(VisionFormatError, match="does not match file suffix"):
            validate_file_format(mismatch_file, workspace)

    def test_validate_file_format_unsupported_extension_rejected(self, workspace: Path):
        """Đuôi không nằm trong danh mục hỗ trợ (.gif) bị từ chối."""
        gif_file = workspace / "anim.gif"
        gif_file.write_bytes(b"GIF89a...")

        with pytest.raises(VisionFormatError, match="Unsupported file extension"):
            validate_file_format(gif_file, workspace)

    @pytest.mark.parametrize(
        "name,payload",
        [
            ("fake.png", b"This is not a real PNG file, just text"),
            ("fake.pdf", b"NOT_A_PDF_CONTENT_HEADER"),
            ("anim.gif", b"GIF89a..."),
        ],
    )
    def test_gate_blocks_fake_media_without_io(
        self,
        workspace: Path,
        test_adapter: str,
        name: str,
        payload: bytes,
    ):
        """Cổng synthetic luôn chặn media giả/tự tạo, không mở file, không spawn."""
        fake = workspace / name
        fake.write_bytes(payload)

        with patch("bin.lib.vision.validate_synthetic_gate", side_effect=VisionBlockedError("synthetic gate")) as mock_gate, \
             patch("subprocess.run") as mock_subprocess:
            with pytest.raises(VisionBlockedError):
                check_vision_gate(
                    files=[fake],
                    model="deepseek-v4.1-flash",
                    adapter=test_adapter,
                    is_synthetic=True,
                    workspace_root=workspace,
                )
            mock_gate.assert_called_once()
            mock_subprocess.assert_not_called()


# ===========================================================================
# 4. CAPABILITIES METADATA & ADAPTER CHECKS (FINDING 1)
# ===========================================================================

class TestCapabilitiesAndAdapters:
    """Kiểm tra capabilities metadata theo model và adapter verification nghiêm ngặt."""

    def test_trusted_model_capabilities(self):
        """Kiểm tra bảng capabilities chuẩn của các model Go."""
        d_caps = get_model_capabilities("deepseek-v4.1-flash")
        assert d_caps["image"] is True
        assert d_caps["pdf"] is False

        g_caps = get_model_capabilities("glm-5.3-flash")
        assert g_caps["image"] is True
        assert g_caps["pdf"] is True

        m_caps = get_model_capabilities("mimo-v2.6-flash")
        assert m_caps["image"] is True
        assert m_caps["pdf"] is False

        p_caps = get_model_capabilities("deepseek-v4-pro")
        assert p_caps["image"] is False
        assert p_caps["pdf"] is False

    def test_contributor_model_always_blocked(self):
        """Model contributor luôn bị chặn đối với vision."""
        with pytest.raises(VisionBlockedError, match="Contributor model .* is blocked"):
            get_model_capabilities("deepseek-v4.1-flash-contributor")

    def test_unknown_model_blocked(self):
        """Model không có trong metadata tin cậy bị chặn (fail-closed)."""
        with pytest.raises(VisionBlockedError, match="capabilities are unverified"):
            get_model_capabilities("unverified-model-slug")

    def test_blank_adapter_blocked_before_file_io(self, workspace: Path):
        """Adapter rỗng, None, hoặc whitespace bị blocked fail-closed TRƯỚC bất kỳ I/O nào."""
        img = create_sample_png(workspace / "img.png")

        for blank in ["", "   ", "\t", None]:
            with patch("builtins.open") as mock_open:
                with pytest.raises(VisionBlockedError, match="Vision adapter must be specified and non-empty; blank adapter is blocked"):
                    check_vision_gate(
                        files=[img],
                        model="deepseek-v4.1-flash",
                        adapter=blank,  # type: ignore[arg-type]
                        is_synthetic=True,
                        workspace_root=workspace,
                    )
                mock_open.assert_not_called()

    def test_verify_adapter_blank_raises(self):
        """Hàm verify_adapter từ chối adapter rỗng fail-closed."""
        with pytest.raises(VisionBlockedError, match="Vision adapter must be specified and non-empty"):
            verify_adapter("")
        with pytest.raises(VisionBlockedError, match="Vision adapter must be specified and non-empty"):
            verify_adapter("   ")

    def test_unverified_adapter_blocked_before_file_io(self, workspace: Path):
        """Adapter chưa verified (hermes giữ block) bị chặn fail-closed trước bất kỳ file I/O nào."""
        img = create_sample_png(workspace / "img.png")

        for unverified in ["hermes", "codex", "agy", "gemini", "grok", "random_adapter"]:
            with patch("builtins.open") as mock_open, \
                 patch("subprocess.run") as mock_subprocess, \
                 patch("shutil.which") as mock_which:
                with pytest.raises(VisionBlockedError, match="is not verified; blocked"):
                    check_vision_gate(
                        files=[img],
                        model="deepseek-v4.1-flash",
                        adapter=unverified,
                        is_synthetic=True,
                        workspace_root=workspace,
                    )
                mock_open.assert_not_called()
                mock_subprocess.assert_not_called()
                mock_which.assert_not_called()

    def test_caller_cannot_self_certify_adapters(self, workspace: Path):
        """Caller không thể tự chứng nhận adapter qua verified_adapters param hay flag."""
        img = create_sample_png(workspace / "img.png")

        # Param verified_adapters đã bị xoá hoàn toàn khỏi public API
        with pytest.raises(TypeError):
            check_vision_gate(
                files=[img],
                model="deepseek-v4.1-flash",
                adapter="opencode",
                is_synthetic=True,
                workspace_root=workspace,
                verified_adapters={"opencode"},  # type: ignore[call-arg]
            )

    def test_registry_frozen_and_pinned(self):
        """Hằng registry là frozenset, chỉ ghim đúng adapter đã xác minh (opencode)."""
        assert isinstance(VERIFIED_VISION_ADAPTERS, frozenset)
        assert VERIFIED_VISION_ADAPTERS == frozenset({"opencode"})
        assert "hermes" not in VERIFIED_VISION_ADAPTERS

    def test_no_repo_root_or_override_hooks_exposed(self):
        """Không có tham số repo_root hay hook override mutable nào trong public API."""
        import inspect

        import bin.lib.vision as vision_module

        for func in (
            vision_module.check_vision_gate,
            vision_module.prepare_vision_input,
            vision_module.validate_synthetic_gate,
        ):
            assert "repo_root" not in inspect.signature(func).parameters

        assert not hasattr(vision_module, "_OVERRIDE")
        assert not hasattr(vision_module, "set_repo_root")
        assert not hasattr(vision_module, "set_trusted_registry")

    def test_test_only_monkeypatched_adapter_allowed(self, synthetic_repo: dict, monkeypatch: pytest.MonkeyPatch):
        """Trong isolated unit test, monkeypatch hằng registry cho phép qua gate an toàn."""
        monkeypatch.setattr("bin.lib.vision.VERIFIED_VISION_ADAPTERS", frozenset({"opencode"}))

        res = check_vision_gate(
            files=[synthetic_repo["png"]],
            model="deepseek-v4.1-flash",
            adapter="opencode",
            is_synthetic=True,
        )
        assert len(res) == 1

    def test_image_rejected_when_model_does_not_support_images(self, synthetic_repo: dict, test_adapter: str):
        """Gửi ảnh cho model có image=false (ví dụ deepseek-v4-pro) bị chặn."""
        with pytest.raises(VisionBlockedError, match="does not support image input"):
            check_vision_gate(
                files=[synthetic_repo["png"]],
                model="deepseek-v4-pro",
                adapter=test_adapter,
                is_synthetic=True,
            )

    def test_pdf_rejected_when_model_supports_neither_pdf_nor_image(self, synthetic_repo: dict, test_adapter: str):
        """Gửi PDF cho model không hỗ trợ cả PDF lẫn image bị chặn."""
        with pytest.raises(VisionBlockedError, match="supports neither PDF nor image input"):
            check_vision_gate(
                files=[synthetic_repo["pdf"]],
                model="deepseek-v4-pro",
                adapter=test_adapter,
                is_synthetic=True,
            )

    def test_pdf_allowed_for_glm_flash_direct(self, synthetic_repo: dict, test_adapter: str):
        """GLM Flash hỗ trợ cả hai (image=true, pdf=true), PDF qua gate trực tiếp."""
        res = check_vision_gate(
            files=[synthetic_repo["pdf"]],
            model="glm-5.3-flash",
            adapter=test_adapter,
            is_synthetic=True,
        )
        assert len(res) == 1
        assert res[0].is_pdf is True


# ===========================================================================
# 5. DEEPSEEK PDF CONVERSION & FINDING 2 GATE
# ===========================================================================

class TestDeepSeekPdfConversion:
    """Kiểm tra pdftoppm subprocess, argv, timeout, numeric order, và Finding 2 gate."""

    def test_public_convert_pdf_to_images_blocked_before_any_io(self, workspace: Path):
        """Hàm public convert_pdf_to_images bị blocked fail-closed TRƯỚC bất kỳ I/O nào,
        không thực thi pdftoppm_bin tùy tiện của caller."""
        pdf = create_sample_pdf(workspace / "doc.pdf")
        out_dir = workspace / "unauthorized_pages"
        fake_binary = "/tmp/malicious_pdftoppm_exploit"

        with patch("subprocess.run") as mock_subprocess, \
             patch("builtins.open") as mock_open, \
             patch("shutil.which") as mock_which:

            with pytest.raises(VisionBlockedError, match="Direct public convert_pdf_to_images is blocked fail-closed"):
                convert_pdf_to_images(
                    pdf_path=pdf,
                    output_dir=out_dir,
                    pdftoppm_bin=fake_binary,
                )

            # Khẳng định không chạy binary, không mở file, không tạo thư mục
            mock_subprocess.assert_not_called()
            mock_open.assert_not_called()
            mock_which.assert_not_called()
            assert not out_dir.exists()

    def test_missing_binary_blocked(self, workspace: Path):
        """Thiếu binary pdftoppm trong internal helper phải bị chặn rõ ràng (fail-closed)."""
        pdf = create_sample_pdf(workspace / "sample.pdf")
        with patch("shutil.which", return_value=None):
            with pytest.raises(VisionBlockedError, match="pdftoppm binary not found"):
                _convert_pdf_to_images(
                    pdf_path=pdf,
                    output_dir=workspace / "pages",
                )

    def test_subprocess_argv_timeout_and_full_res_flags(self, workspace: Path):
        """Kiểm tra lệnh gọi subprocess argv list (không shell=True), timeout, full res.

        Output luôn nằm trong private dir mới do helper tự tạo (TMPDIR), nên
        pdftoppm giả phải ghi trang vào đúng ``out_prefix`` trong argv.
        """
        pdf = create_sample_pdf(workspace / "doc.pdf")
        written_dirs: list[Path] = []

        def fake_run(cmd, **kwargs):
            out_prefix = Path(cmd[-1])
            written_dirs.append(out_prefix.parent)
            create_sample_png(out_prefix.parent / f"{out_prefix.name}-1.png")
            return MagicMock(returncode=0, stdout=b"", stderr=b"")

        with patch("shutil.which", return_value="/usr/local/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_run) as mock_run:

            res = _convert_pdf_to_images(
                pdf_path=pdf,
                prefix="doc",
                dpi=200,
                timeout=25,
            )

            mock_run.assert_called_once()
            called_args, called_kwargs = mock_run.call_args
            cmd = called_args[0]

            # Kiểm tra an toàn: argv list, không shell
            assert isinstance(cmd, list)
            assert "shell" not in called_kwargs or called_kwargs["shell"] is False
            assert called_kwargs.get("timeout") == 25

            # Kiểm tra cờ tách trang: full res (-png, -r 200), KHÔNG có -contact-sheet
            assert "-png" in cmd
            assert "-r" in cmd
            assert "200" in cmd
            assert "-contact-sheet" not in cmd

            assert [p.name for p in res] == ["doc-1.png"]
            assert len(written_dirs) == 1
            conv_dir = written_dirs[0]
            assert conv_dir.name.startswith("polykit-vision-")
            assert res[0].parent == conv_dir
            assert not str(conv_dir).startswith(str(workspace.resolve()))

    def test_numeric_order_sorting(self, workspace: Path):
        """Đảm bảo thứ tự trang theo số tự nhiên (1, 2, ..., 10, 11),
        không bị xếp sai thứ tự theo bảng chữ cái (1, 10, 11, 2)."""
        pdf = create_sample_pdf(workspace / "multi.pdf")
        page_nums = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

        def fake_run(cmd, **kwargs):
            out_prefix = Path(cmd[-1])
            # Ghi lộn xộn để chắc chắn thứ tự do code sắp, không do thứ tự ghi.
            for n in sorted(page_nums, reverse=True):
                create_sample_png(out_prefix.parent / f"{out_prefix.name}-{n}.png")
            return MagicMock(returncode=0)

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_run):

            res = _convert_pdf_to_images(
                pdf_path=pdf,
                prefix="page",
            )

            # Khẳng định thứ tự trả về khớp đúng số trang tự nhiên
            expected_names = [f"page-{n}.png" for n in page_nums]
            actual_names = [p.name for p in res]
            assert actual_names == expected_names
            # Khẳng định không bị lỗi xếp chữ cái (page-10 trước page-2)
            assert actual_names.index("page-2.png") < actual_names.index("page-10.png")

    def test_converter_nonzero_exit_code_failure(self, workspace: Path):
        """pdftoppm trả về exit code khác 0 -> VisionConversionError."""
        pdf = create_sample_pdf(workspace / "corrupt.pdf")
        fake_proc = MagicMock(returncode=1, stderr=b"Syntax Error: Invalid xref table")

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", return_value=fake_proc):

            with pytest.raises(VisionConversionError, match="pdftoppm exited with nonzero"):
                _convert_pdf_to_images(
                    pdf_path=pdf,
                )

    def test_converter_timeout_failure(self, workspace: Path):
        """pdftoppm bị timeout -> VisionConversionError."""
        pdf = create_sample_pdf(workspace / "timeout.pdf")

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["pdftoppm"], timeout=5)):

            with pytest.raises(VisionConversionError, match="timed out"):
                _convert_pdf_to_images(
                    pdf_path=pdf,
                    timeout=5,
                )

    def test_converter_empty_output_failure(self, workspace: Path):
        """pdftoppm exit 0 nhưng không sinh ra file ảnh nào -> VisionConversionError."""
        pdf = create_sample_pdf(workspace / "empty_doc.pdf")
        fake_proc = MagicMock(returncode=0)

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", return_value=fake_proc):

            with pytest.raises(VisionConversionError, match="produced no image pages"):
                _convert_pdf_to_images(
                    pdf_path=pdf,
                )


# ===========================================================================
# 6. HIGH-LEVEL PREPARATION API & INTEGRATION
# ===========================================================================

class TestPrepareVisionInput:
    """Kiểm tra luồng tích hợp prepare_vision_input."""

    def test_prepare_vision_input_blank_adapter_blocked_fail_closed(self, workspace: Path):
        """Gọi prepare_vision_input mà không có adapter hoặc adapter rỗng bị chặn ngay, không đọc file."""
        pdf = create_sample_pdf(workspace / "doc.pdf")

        with patch("builtins.open") as mock_open, \
             patch("subprocess.run") as mock_subprocess:

            with pytest.raises(VisionBlockedError, match="blank adapter is blocked"):
                prepare_vision_input(
                    files=[pdf],
                    model="deepseek-v4.1-flash",
                    is_synthetic=True,
                    workspace_root=workspace,
                )

            mock_open.assert_not_called()
            mock_subprocess.assert_not_called()

    def test_prepare_vision_input_unverified_adapter_blocked(self, workspace: Path):
        """prepare_vision_input với adapter chưa verified (hermes) bị chặn fail-closed."""
        pdf = create_sample_pdf(workspace / "doc.pdf")

        with patch("builtins.open") as mock_open:
            with pytest.raises(VisionBlockedError, match="is not verified; blocked"):
                prepare_vision_input(
                    files=[pdf],
                    model="deepseek-v4.1-flash",
                    adapter="hermes",
                    is_synthetic=True,
                    workspace_root=workspace,
                )
            mock_open.assert_not_called()

    def test_prepare_vision_input_actual_repo_trusted_pdf_split(self, tmp_path: Path):
        """PDF trusted thật trong repo: DeepSeek tách trang qua prepare (helper nội bộ)."""
        from bin.lib import vision as vision_module

        repo_pdf = vision_module.REAL_REPO_ROOT / "bench" / "vision" / "synthetic" / "multipage_contract.pdf"
        assert repo_pdf.is_file(), "repo synthetic PDF phải tồn tại để test dương tính"

        written_dirs: list[Path] = []

        def fake_run(cmd, **kwargs):
            out_prefix = Path(cmd[-1])
            written_dirs.append(out_prefix.parent)
            for n in (1, 2):
                create_sample_png(out_prefix.parent / f"{out_prefix.name}-{n}.png")
            return MagicMock(returncode=0)

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_run):
            result_paths = prepare_vision_input(
                files=[repo_pdf],
                model="deepseek-v4.1-flash",
                adapter="opencode",
                is_synthetic=True,
            )

        assert [p.name for p in result_paths] == [
            "multipage_contract-1.png",
            "multipage_contract-2.png",
        ]
        # Page nằm trong private dir mới (TMPDIR), không nằm trong repo/tmp_path.
        conv_dir = written_dirs[0]
        assert conv_dir.name.startswith("polykit-vision-")
        assert {p.parent for p in result_paths} == {conv_dir}
        assert not str(conv_dir).startswith(str(tmp_path.resolve()))

    def test_prepare_vision_input_rejects_repo_root_bypass(self):
        """Không có tham số repo_root để trỏ cổng sang repo khác."""
        with pytest.raises(TypeError):
            prepare_vision_input(
                files=["page_01_narrow_table.png"],
                model="deepseek-v4.1-flash",
                adapter="opencode",
                is_synthetic=True,
                repo_root=Path("/tmp/fake-repo"),  # type: ignore[call-arg]
            )

    def test_prepare_vision_input_deepseek_converts_pdf(self, synthetic_repo: dict, test_adapter: str):
        """DeepSeek V4.1 Flash không nhận trực tiếp PDF, tự động gọi helper tách trang sau gate."""
        written_dirs: list[Path] = []

        def fake_run(cmd, **kwargs):
            out_prefix = Path(cmd[-1])
            written_dirs.append(out_prefix.parent)
            for n in (1, 2):
                create_sample_png(out_prefix.parent / f"{out_prefix.name}-{n}.png")
            return MagicMock(returncode=0)

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_run):

            result_paths = prepare_vision_input(
                files=[synthetic_repo["pdf"]],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
            )

            assert len(result_paths) == 2
            assert result_paths[0].name == "fixture_doc-1.png"
            assert result_paths[1].name == "fixture_doc-2.png"
            # Không ghi vào repo fixture: mọi page nằm trong private TMPDIR.
            conv_dir = written_dirs[0]
            assert conv_dir.name.startswith("polykit-vision-")
            assert {p.parent for p in result_paths} == {conv_dir}
            assert synthetic_repo["root"] not in conv_dir.parents

    def test_prepare_vision_input_glm_keeps_pdf_direct(self, synthetic_repo: dict, test_adapter: str):
        """GLM Flash nhận PDF trực tiếp, không gọi pdftoppm."""
        with patch("subprocess.run") as mock_subprocess:
            result_paths = prepare_vision_input(
                files=[synthetic_repo["pdf"]],
                model="glm-5.3-flash",
                adapter=test_adapter,
                is_synthetic=True,
            )

            mock_subprocess.assert_not_called()
            assert len(result_paths) == 1
            assert result_paths[0] == synthetic_repo["pdf"].resolve()

    def test_prepare_vision_input_rejects_bypass_params(self, workspace: Path):
        """prepare_vision_input từ chối các tham số tự chứng nhận hoặc pdftoppm_bin."""
        pdf = create_sample_pdf(workspace / "doc.pdf")

        with pytest.raises(TypeError):
            prepare_vision_input(
                files=[pdf],
                model="deepseek-v4.1-flash",
                adapter="opencode",
                is_synthetic=True,
                verified_adapters={"opencode"},  # type: ignore[call-arg]
            )

        with pytest.raises(TypeError):
            prepare_vision_input(
                files=[pdf],
                model="deepseek-v4.1-flash",
                adapter="opencode",
                is_synthetic=True,
                pdftoppm_bin="/fake/bin",  # type: ignore[call-arg]
            )

    def test_prepare_vision_input_sensitive_blocks_before_conversion(self, workspace: Path, test_adapter: str):
        """Khi gọi prepare_vision_input với file sensitive, gate chặn ngay trước khi mở hay chuyển đổi."""
        pdf = create_sample_pdf(workspace / "sensitive_statement.pdf")

        with patch("subprocess.run") as mock_subprocess, \
             patch("builtins.open") as mock_open:

            with pytest.raises(VisionBlockedError):
                prepare_vision_input(
                    files=[pdf],
                    model="deepseek-v4.1-flash",
                    adapter=test_adapter,
                    is_synthetic=False,
                    workspace_root=workspace,
                )

            mock_subprocess.assert_not_called()
            mock_open.assert_not_called()