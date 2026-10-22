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

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bin.lib.vision import (
    DEFAULT_MAX_FILE_BYTES,
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
    verify_adapter,
)


# ===========================================================================
# Fixtures & Helpers
# ===========================================================================

TEST_ADAPTER_NAME = "test_verified_adapter"


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
        """Cờ --allow-sensitive-vision một mình không đủ nếu thiếu confirmation."""
        sensitive_file = workspace / "id_card.png"
        create_sample_png(sensitive_file)

        with patch("builtins.open") as mock_open, \
             patch("subprocess.run") as mock_subprocess:

            with pytest.raises(VisionBlockedError, match="--allow-sensitive-vision alone is not sufficient"):
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

    def test_arbitrary_string_consent_rejected(self, workspace: Path):
        """KHÔNG nhận chuỗi string bất kỳ làm consent (ví dụ 'yes', 'Tuan', 'confirm')."""
        sensitive_file = workspace / "passport.jpg"
        create_sample_jpeg(sensitive_file)

        for fake_string in ["yes", "confirm", "I agree", "Tuan approved", "true", "1"]:
            with patch("builtins.open") as mock_open:
                with pytest.raises(VisionBlockedError, match="Arbitrary string consent is rejected"):
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
            with pytest.raises(VisionBlockedError, match="trusted UI confirmation is not supported yet"):
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
        """Confirmation không được kế thừa qua retry hoặc failover."""
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
        with pytest.raises(VisionBlockedError, match="Confirmation cannot be inherited"):
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
        with pytest.raises(VisionBlockedError, match="Confirmation cannot be inherited"):
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
        """Confirmation bị từ chối nếu không khớp exact files, model hoặc provider."""
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
        with pytest.raises(VisionBlockedError, match="files do not match"):
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
        with pytest.raises(VisionBlockedError, match="model does not match"):
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
        with pytest.raises(VisionBlockedError, match="provider does not match"):
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

        with pytest.raises(VisionBlockedError, match="Confirmation has already been consumed"):
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
            with pytest.raises(VisionBlockedError, match="Sensitive or undeclared synthetic vision data is blocked"):
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
    """Kiểm tra path thường, cấm symlink, cấm path outside workspace, hỗ trợ khoảng trắng."""

    def test_valid_synthetic_regular_file(self, workspace: Path, test_adapter: str):
        """File hợp lệ trong workspace và tuyên bố synthetic."""
        img = create_sample_png(workspace / "test.png")
        res = check_vision_gate(
            files=[img],
            model="deepseek-v4.1-flash",
            adapter=test_adapter,
            is_synthetic=True,
            workspace_root=workspace,
        )
        assert len(res) == 1
        assert res[0].mime_type == "image/png"
        assert res[0].is_synthetic is True

    def test_symlink_blocked(self, workspace: Path, test_adapter: str):
        """Symlink bị chặn tuyệt đối (VisionSecurityError)."""
        real_img = create_sample_png(workspace / "real.png")
        link_img = workspace / "symlink_to_real.png"
        try:
            link_img.symlink_to(real_img)
        except OSError:
            pytest.skip("Filesystem does not support symlinks")

        with pytest.raises(VisionSecurityError, match="Symlinks are blocked"):
            check_vision_gate(
                files=[link_img],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
            )

    def test_path_outside_workspace_blocked(self, workspace: Path, tmp_path: Path, test_adapter: str):
        """Path nằm ngoài workspace root được chỉ định bị chặn (VisionSecurityError)."""
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        outside_file = create_sample_png(outside_dir / "external.png")

        with pytest.raises(VisionSecurityError, match="outside allowed workspace"):
            check_vision_gate(
                files=[outside_file],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
            )

    def test_path_traversal_blocked(self, workspace: Path, test_adapter: str):
        """Thử dùng traversal ../.. thoát khỏi workspace."""
        traversal_path = workspace / "sub" / ".." / ".." / "escape.png"
        with pytest.raises(VisionSecurityError):
            check_vision_gate(
                files=[traversal_path],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
            )

    def test_path_with_whitespace_supported(self, workspace: Path, test_adapter: str):
        """Đường dẫn có khoảng trắng (spaces) được hỗ trợ nguyên vẹn, không bị tách từ."""
        spaced_dir = workspace / "my synthetic documents"
        spaced_dir.mkdir()
        spaced_file = create_sample_png(spaced_dir / "diagram draft v1.png")

        res = check_vision_gate(
            files=[spaced_file],
            model="deepseek-v4.1-flash",
            adapter=test_adapter,
            is_synthetic=True,
            workspace_root=workspace,
        )
        assert len(res) == 1
        assert res[0].path == spaced_file.resolve()
        assert "diagram draft v1.png" in str(res[0].path)

    def test_missing_file_rejected(self, workspace: Path, test_adapter: str):
        """File không tồn tại bị từ chối (VisionFormatError)."""
        missing = workspace / "non_existent.png"
        with pytest.raises(VisionFormatError, match="File not found"):
            check_vision_gate(
                files=[missing],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
            )

    def test_directory_rejected(self, workspace: Path, test_adapter: str):
        """Thư mục truyền vào làm attachment bị từ chối (VisionFormatError)."""
        d = workspace / "some_dir.png"
        d.mkdir()
        with pytest.raises(VisionFormatError, match="Not a regular file"):
            check_vision_gate(
                files=[d],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
            )

    def test_empty_file_rejected(self, workspace: Path, test_adapter: str):
        """File 0 bytes bị từ chối (VisionFormatError)."""
        empty_file = workspace / "empty.png"
        empty_file.touch()
        with pytest.raises(VisionFormatError, match="File is empty"):
            check_vision_gate(
                files=[empty_file],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
            )

    def test_quota_size_limit_exceeded(self, workspace: Path, test_adapter: str):
        """File vượt hạn dung lượng bị chặn (VisionQuotaError)."""
        oversized = workspace / "oversized.png"
        with oversized.open("wb") as f:
            f.write(PNG_MAGIC + b"X" * 1024)

        with pytest.raises(VisionQuotaError, match="exceeds maximum limit"):
            check_vision_gate(
                files=[oversized],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
                max_bytes=500,  # Limit nhỏ hơn 1024
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

    def test_png_suffix_with_fake_content_rejected(self, workspace: Path, test_adapter: str):
        """Đuôi .png nhưng nội dung là text rác bị từ chối."""
        fake_png = workspace / "fake.png"
        fake_png.write_text("This is not a real PNG file, just text")

        with pytest.raises(VisionFormatError, match="magic bytes do not match"):
            check_vision_gate(
                files=[fake_png],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
            )

    def test_pdf_suffix_without_pdf_magic_rejected(self, workspace: Path, test_adapter: str):
        """Đuôi .pdf nhưng thiếu magic %PDF bị từ chối."""
        fake_pdf = workspace / "fake.pdf"
        fake_pdf.write_bytes(b"NOT_A_PDF_CONTENT_HEADER")

        with pytest.raises(VisionFormatError, match="magic bytes do not match"):
            check_vision_gate(
                files=[fake_pdf],
                model="glm-5.3-flash",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
            )

    def test_jpeg_suffix_with_png_content_mismatch_rejected(self, workspace: Path, test_adapter: str):
        """Nội dung là PNG magic nhưng đuôi lại đặt là .jpg."""
        mismatch_file = workspace / "wrong_extension.jpg"
        with mismatch_file.open("wb") as f:
            f.write(PNG_MAGIC + b"some png content")

        with pytest.raises(VisionFormatError, match="does not match file suffix"):
            check_vision_gate(
                files=[mismatch_file],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
            )

    def test_unsupported_extension_rejected(self, workspace: Path, test_adapter: str):
        """Đuôi không nằm trong danh mục hỗ trợ (.gif, .exe, .sh) bị từ chối."""
        gif_file = workspace / "anim.gif"
        gif_file.write_bytes(b"GIF89a...")

        with pytest.raises(VisionFormatError, match="Unsupported file extension"):
            check_vision_gate(
                files=[gif_file],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
            )


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
        """Adapter chưa verified bị blocked mặc định fail-closed trước bất kỳ file I/O nào."""
        img = create_sample_png(workspace / "img.png")

        for unverified in ["hermes", "codex", "agy", "gemini", "grok", "opencode", "random_adapter"]:
            with patch("builtins.open") as mock_open:
                with pytest.raises(VisionBlockedError, match="is not verified; blocked"):
                    check_vision_gate(
                        files=[img],
                        model="deepseek-v4.1-flash",
                        adapter=unverified,
                        is_synthetic=True,
                        workspace_root=workspace,
                    )
                mock_open.assert_not_called()

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

    def test_registry_frozen_and_empty_by_default(self):
        """Hằng registry là frozenset và mặc định rỗng hoàn toàn."""
        assert isinstance(VERIFIED_VISION_ADAPTERS, frozenset)
        assert len(VERIFIED_VISION_ADAPTERS) == 0

    def test_test_only_monkeypatched_adapter_allowed(self, workspace: Path, monkeypatch: pytest.MonkeyPatch):
        """Trong isolated unit test, monkeypatch hằng registry cho phép qua gate an toàn."""
        img = create_sample_png(workspace / "img.png")
        monkeypatch.setattr("bin.lib.vision.VERIFIED_VISION_ADAPTERS", frozenset({"opencode"}))

        res = check_vision_gate(
            files=[img],
            model="deepseek-v4.1-flash",
            adapter="opencode",
            is_synthetic=True,
            workspace_root=workspace,
        )
        assert len(res) == 1

    def test_image_rejected_when_model_does_not_support_images(self, workspace: Path, test_adapter: str):
        """Gửi ảnh cho model có image=false (ví dụ deepseek-v4-pro) bị chặn."""
        img = create_sample_png(workspace / "test.png")
        with pytest.raises(VisionBlockedError, match="does not support image input"):
            check_vision_gate(
                files=[img],
                model="deepseek-v4-pro",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
            )

    def test_pdf_rejected_when_model_supports_neither_pdf_nor_image(self, workspace: Path, test_adapter: str):
        """Gửi PDF cho model không hỗ trợ cả PDF lẫn image bị chặn."""
        pdf = create_sample_pdf(workspace / "doc.pdf")
        with pytest.raises(VisionBlockedError, match="supports neither PDF nor image input"):
            check_vision_gate(
                files=[pdf],
                model="deepseek-v4-pro",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
            )

    def test_pdf_allowed_for_glm_flash_direct(self, workspace: Path, test_adapter: str):
        """GLM Flash hỗ trợ cả hai (image=true, pdf=true), PDF qua gate trực tiếp."""
        pdf = create_sample_pdf(workspace / "direct.pdf")
        res = check_vision_gate(
            files=[pdf],
            model="glm-5.3-flash",
            adapter=test_adapter,
            is_synthetic=True,
            workspace_root=workspace,
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
        """Kiểm tra lệnh gọi subprocess argv list (không shell=True), timeout, full res."""
        pdf = create_sample_pdf(workspace / "doc.pdf")
        out_dir = workspace / "out_pages"
        out_dir.mkdir()

        # Tạo file ảnh giả để hàm tìm thấy output
        p1 = out_dir / "doc-1.png"
        create_sample_png(p1)

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = b""
        fake_proc.stderr = b""

        with patch("shutil.which", return_value="/usr/local/bin/pdftoppm"), \
             patch("subprocess.run", return_value=fake_proc) as mock_run:

            res = _convert_pdf_to_images(
                pdf_path=pdf,
                output_dir=out_dir,
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
            assert res == [p1]

    def test_numeric_order_sorting(self, workspace: Path):
        """Đảm bảo thứ tự trang theo số tự nhiên (1, 2, ..., 10, 11),
        không bị xếp sai thứ tự theo bảng chữ cái (1, 10, 11, 2)."""
        pdf = create_sample_pdf(workspace / "multi.pdf")
        out_dir = workspace / "multi_pages"
        out_dir.mkdir()

        # Tạo các trang từ 1 đến 12
        page_nums = [1, 2, 3, 9, 10, 11, 12]
        created_pages = []
        for n in page_nums:
            p = create_sample_png(out_dir / f"page-{n}.png")
            created_pages.append(p)

        fake_proc = MagicMock(returncode=0)

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", return_value=fake_proc):

            res = _convert_pdf_to_images(
                pdf_path=pdf,
                output_dir=out_dir,
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
                    output_dir=workspace / "pages",
                )

    def test_converter_timeout_failure(self, workspace: Path):
        """pdftoppm bị timeout -> VisionConversionError."""
        pdf = create_sample_pdf(workspace / "timeout.pdf")

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["pdftoppm"], timeout=5)):

            with pytest.raises(VisionConversionError, match="timed out"):
                _convert_pdf_to_images(
                    pdf_path=pdf,
                    output_dir=workspace / "pages",
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
                    output_dir=workspace / "pages",
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
        """prepare_vision_input với adapter chưa verified bị chặn fail-closed."""
        pdf = create_sample_pdf(workspace / "doc.pdf")

        with patch("builtins.open") as mock_open:
            with pytest.raises(VisionBlockedError, match="is not verified; blocked"):
                prepare_vision_input(
                    files=[pdf],
                    model="deepseek-v4.1-flash",
                    adapter="opencode",
                    is_synthetic=True,
                    workspace_root=workspace,
                )
            mock_open.assert_not_called()

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

    def test_prepare_vision_input_deepseek_converts_pdf(self, workspace: Path, test_adapter: str):
        """DeepSeek V4.1 Flash không nhận trực tiếp PDF, tự động gọi helper tách trang sau gate."""
        pdf = create_sample_pdf(workspace / "invoice.pdf")
        conv_dir = workspace / "converted_out"
        conv_dir.mkdir()
        p1 = create_sample_png(conv_dir / "invoice-1.png")
        p2 = create_sample_png(conv_dir / "invoice-2.png")

        fake_proc = MagicMock(returncode=0)

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", return_value=fake_proc):

            result_paths = prepare_vision_input(
                files=[pdf],
                model="deepseek-v4.1-flash",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
                output_dir=conv_dir,
            )

            assert len(result_paths) == 2
            assert result_paths[0].name == "invoice-1.png"
            assert result_paths[1].name == "invoice-2.png"

    def test_prepare_vision_input_glm_keeps_pdf_direct(self, workspace: Path, test_adapter: str):
        """GLM Flash nhận PDF trực tiếp, không gọi pdftoppm."""
        pdf = create_sample_pdf(workspace / "report.pdf")

        with patch("subprocess.run") as mock_subprocess:
            result_paths = prepare_vision_input(
                files=[pdf],
                model="glm-5.3-flash",
                adapter=test_adapter,
                is_synthetic=True,
                workspace_root=workspace,
            )

            mock_subprocess.assert_not_called()
            assert len(result_paths) == 1
            assert result_paths[0] == pdf.resolve()

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
