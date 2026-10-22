"""Security tests cho cổng synthetic vision (manifest + pinned registry).

Nguyên tắc được kiểm:
1. Chỉ file nằm trong ``bench/vision/synthetic/`` của module root thật, khớp
   manifest generator và pinned registry SHA-256 mới đi qua cổng.
2. Manifest sai/hỏng/giả (schema bool, duplicate, path lạ, hash lệch, generator
   khác, entry không khai báo) đều ``vision_blocked``.
3. Symlink ở file, manifest hay ancestor directory đều bị chặn.
4. Cờ sensitive, adapter lạ, model lạ bị chặn TRƯỚC probe/open/subprocess;
   runner không được gọi (runner=0).
5. Không có đường bypass public (repo_root, verified_adapters, pdftoppm_bin).
6. Fixture dùng payload cố định + hash deterministic; file lạ không tự hợp lệ.
7. Dương tính thật: PNG/PDF trong repo hiện tại qua cổng, DeepSeek tách PDF.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import bin.lib.vision as vision
from bin.lib.vision import (
    EXPECTED_MANIFEST_GENERATOR,
    EXPECTED_MANIFEST_SCHEMA_VERSION,
    PDF_MAGIC,
    PNG_MAGIC,
    VisionBlockedError,
    VisionFormatError,
    VisionSecurityError,
    check_vision_gate,
    convert_pdf_to_images,
    prepare_vision_input,
    validate_synthetic_gate,
)

DEEPSEEK = "deepseek-v4.1-flash"
GLM = "glm-5.3-flash"
OPENCODE = "opencode"

# Payload cố định: hash fixture deterministic qua mọi lần chạy.
PNG_PAYLOAD = PNG_MAGIC + b"polykit-gate-fixture-png-deterministic"
PDF_PAYLOAD = PDF_MAGIC + b"-1.7\npolykit-gate-fixture-pdf-deterministic\n"
PNG_SHA = hashlib.sha256(PNG_PAYLOAD).hexdigest()
PDF_SHA = hashlib.sha256(PDF_PAYLOAD).hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Fixture repo + manifest helpers
# ---------------------------------------------------------------------------

def _entries(registry: dict[str, dict]) -> list[dict]:
    return [
        {
            "path": name,
            "rel_path": rec["rel_path"],
            "format": rec["format"],
            "bytes": rec["bytes"],
            "sha256": rec["sha256"],
        }
        for name, rec in registry.items()
    ]


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    root = (tmp_path / "repo").resolve()
    root.mkdir()
    synth = root / "bench" / "vision" / "synthetic"
    synth.mkdir(parents=True)

    png = synth / "page_a.png"
    png.write_bytes(PNG_PAYLOAD)
    pdf = synth / "doc_a.pdf"
    pdf.write_bytes(PDF_PAYLOAD)

    registry = {
        "page_a.png": {
            "sha256": PNG_SHA,
            "bytes": len(PNG_PAYLOAD),
            "format": "PNG",
            "rel_path": "bench/vision/synthetic/page_a.png",
        },
        "doc_a.pdf": {
            "sha256": PDF_SHA,
            "bytes": len(PDF_PAYLOAD),
            "format": "PDF",
            "rel_path": "bench/vision/synthetic/doc_a.pdf",
        },
    }
    manifest = {
        "schema_version": EXPECTED_MANIFEST_SCHEMA_VERSION,
        "generator": EXPECTED_MANIFEST_GENERATOR,
        "files": _entries(registry),
    }
    (synth / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    monkeypatch.setattr(vision, "REAL_REPO_ROOT", root)
    monkeypatch.setattr(vision, "TRUSTED_SYNTHETIC_REGISTRY", registry)

    return {
        "root": root,
        "synth": synth,
        "png": png,
        "pdf": pdf,
        "registry": registry,
        "manifest": manifest,
    }


def load_manifest(repo: dict) -> dict:
    return json.loads((repo["synth"] / "manifest.json").read_text(encoding="utf-8"))


def write_manifest(repo: dict, manifest: dict) -> None:
    (repo["synth"] / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def assert_blocked_before_io(callable_, *exc_types):
    """Chặn TRƯỚC mọi file I/O, không probe/spawn.

    Chỉ dùng cho các nhánh policy chạy TRƯỚC ``validate_synthetic_gate``:
    sensitive/undeclared, adapter chưa verify, model chưa xác minh.
    """
    with patch("builtins.open") as mock_open, \
         patch("os.stat") as mock_stat, \
         patch("subprocess.run") as mock_run, \
         patch("shutil.which") as mock_which:
        with pytest.raises(exc_types or (VisionBlockedError,)):
            callable_()
        mock_open.assert_not_called()
        mock_stat.assert_not_called()
        mock_run.assert_not_called()
        mock_which.assert_not_called()


def assert_no_runner(callable_, *exc_types):
    """Chạy callable, khẳng định bị chặn và không hề spawn/probe (runner = 0).

    Spy ``os.stat`` phải giữ ``wraps=os.stat``: ``pathlib.Path.stat`` gọi thẳng
    ``os.stat``, mock trần trả MagicMock khiến ``Path.is_symlink()`` nổ
    ``TypeError: an integer is required`` (st_mode là MagicMock) TRƯỚC khi cổng
    kịp từ chối — test fail vì lý do giả tạo chứ không phải vì gate hở.

    KHÔNG assert "không file I/O" ở đây: validation synthetic bản chất phải đọc
    manifest và băm nội dung file. Chỉ assert không spawn subprocess/probe binary.
    """
    with patch("os.stat", wraps=os.stat), \
         patch("subprocess.run") as mock_run, \
         patch("shutil.which") as mock_which:
        with pytest.raises(exc_types or (VisionBlockedError,)):
            callable_()
        mock_run.assert_not_called()
        mock_which.assert_not_called()


# ---------------------------------------------------------------------------
# 1. Fixture integrity — deterministic trusted record
# ---------------------------------------------------------------------------

class TestFixtureRegistryIntegrity:
    def test_fixture_hashes_are_deterministic_known_values(self, repo: dict):
        assert repo["registry"]["page_a.png"]["sha256"] == PNG_SHA
        assert repo["registry"]["doc_a.pdf"]["sha256"] == PDF_SHA
        assert len(PNG_SHA) == 64 and PNGSHA_IS_HEX()
        assert sha256_hex(PNG_PAYLOAD) == PNG_SHA

    def test_manifest_entries_match_fixture_registry(self, repo: dict):
        manifest = load_manifest(repo)
        by_name = {entry["path"]: entry for entry in manifest["files"]}
        for name, record in repo["registry"].items():
            assert by_name[name]["sha256"] == record["sha256"]
            assert by_name[name]["bytes"] == record["bytes"]

    def test_arbitrary_file_in_synthetic_dir_not_trusted(self, repo: dict):
        """File tự tạo cùng thư mục nhưng không khai registry/manifest vẫn bị chặn."""
        rogue = repo["synth"] / "rogue.png"
        rogue.write_bytes(PNG_MAGIC + b"rogue content")
        assert_no_runner(
            lambda: validate_synthetic_gate([rogue]),
            VisionBlockedError,
        )


def PNGSHA_IS_HEX() -> bool:
    return all(c in "0123456789abcdef" for c in PNG_SHA)


# ---------------------------------------------------------------------------
# 2. Dương tính
# ---------------------------------------------------------------------------

class TestPositivePaths:
    def test_valid_png_passes(self, repo: dict):
        result = check_vision_gate(
            files=[repo["png"]], model=DEEPSEEK, adapter=OPENCODE, is_synthetic=True
        )
        assert len(result) == 1
        assert result[0].mime_type == "image/png"
        assert result[0].is_synthetic is True

    def test_valid_pdf_passes_for_glm(self, repo: dict):
        result = check_vision_gate(
            files=[repo["pdf"]], model=GLM, adapter=OPENCODE, is_synthetic=True
        )
        assert len(result) == 1
        assert result[0].is_pdf is True

    def test_multiple_valid_files_pass(self, repo: dict):
        result = check_vision_gate(
            files=[repo["png"], repo["pdf"]], model=GLM, adapter=OPENCODE, is_synthetic=True
        )
        assert [att.mime_type for att in result] == ["image/png", "application/pdf"]

    def test_relative_filename_resolves_inside_fixed_dir(self, repo: dict):
        result = check_vision_gate(
            files=["page_a.png"], model=DEEPSEEK, adapter=OPENCODE, is_synthetic=True
        )
        assert result[0].path.name == "page_a.png"

    def test_actual_repo_png_passes(self):
        """Dương tính thật: PNG generator trong repo hiện tại."""
        actual = vision.REAL_REPO_ROOT / "bench" / "vision" / "synthetic" / "page_01_narrow_table.png"
        assert actual.is_file(), "repo phải có artifact synthetic đã commit/kết xuất"

        result = check_vision_gate(
            files=[actual], model=DEEPSEEK, adapter=OPENCODE, is_synthetic=True
        )
        assert result[0].mime_type == "image/png"

    def test_actual_repo_pdf_passes_for_glm(self):
        """Dương tính thật: PDF nhiều trang trong repo qua cổng cho GLM."""
        actual = vision.REAL_REPO_ROOT / "bench" / "vision" / "synthetic" / "multipage_contract.pdf"
        assert actual.is_file()

        result = check_vision_gate(
            files=[actual], model=GLM, adapter=OPENCODE, is_synthetic=True
        )
        assert result[0].is_pdf is True

    def test_actual_repo_pinned_registry_matches_manifest(self):
        """Pin trong vision.py phải khớp manifest generator đã commit (page03 hash mới)."""
        synth = vision.REAL_REPO_ROOT / "bench" / "vision" / "synthetic"
        manifest = json.loads((synth / "manifest.json").read_text(encoding="utf-8"))

        declared = {entry["path"]: entry for entry in manifest["files"]}
        assert set(declared) == set(vision.TRUSTED_SYNTHETIC_REGISTRY)

        for name, record in vision.TRUSTED_SYNTHETIC_REGISTRY.items():
            assert declared[name]["sha256"] == record["sha256"], f"sha256 pin lệch: {name}"
            assert declared[name]["bytes"] == record["bytes"], f"bytes pin lệch: {name}"
            assert declared[name]["format"] == record["format"]


# ---------------------------------------------------------------------------
# 3. Manifest malformed / giả / tamper
# ---------------------------------------------------------------------------

def _mutate(manifest: dict, mutator) -> dict:
    mutator(manifest)
    return manifest


class TestManifestValidation:
    def test_malformed_json_blocked(self, repo: dict):
        (repo["synth"] / "manifest.json").write_text("{not json", encoding="utf-8")
        assert_no_runner(lambda: validate_synthetic_gate([repo["png"]]), VisionBlockedError)

    def test_manifest_root_not_object_blocked(self, repo: dict):
        (repo["synth"] / "manifest.json").write_text("[1, 2, 3]", encoding="utf-8")
        assert_no_runner(lambda: validate_synthetic_gate([repo["png"]]), VisionBlockedError)

    @pytest.mark.parametrize(
        "mutator",
        [
            lambda m: m.__setitem__("schema_version", 2),
            lambda m: m.__setitem__("schema_version", True),  # bool: True == 1 nếu chỉ so ==
            lambda m: m.__setitem__("schema_version", "1"),
            lambda m: m.__setitem__("schema_version", None),
            lambda m: m.__setitem__("generator", "bench/vision/other_generate.py"),
            lambda m: m.pop("generator"),
            lambda m: m.__setitem__("files", []),
            lambda m: m.__setitem__("files", "page_a.png"),
            lambda m: m.__setitem__("files", ["page_a.png"]),
        ],
    )
    def test_bad_header_or_files_shape_blocked(self, repo: dict, mutator):
        write_manifest(repo, _mutate(load_manifest(repo), mutator))
        assert_no_runner(lambda: validate_synthetic_gate([repo["png"]]), VisionBlockedError)

    @pytest.mark.parametrize(
        "mutator",
        [
            # path không phải tên file trần
            lambda m: m["files"][0].__setitem__("path", "sub/page_a.png"),
            lambda m: m["files"][0].__setitem__("path", "../page_a.png"),
            lambda m: m["files"][0].__setitem__("path", "/abs/page_a.png"),
            lambda m: m["files"][0].__setitem__("path", 123),
            # thiếu/khai man hash
            lambda m: m["files"][0].pop("sha256"),
            lambda m: m["files"][0].__setitem__("sha256", "zz"),
            lambda m: m["files"][0].__setitem__("sha256", "0" * 64),
            # bytes sai kiểu hoặc sai giá trị
            lambda m: m["files"][0].__setitem__("bytes", True),
            lambda m: m["files"][0].__setitem__("bytes", len(PNG_PAYLOAD) + 1),
            lambda m: m["files"][0].pop("bytes"),
            # format / rel_path lệch
            lambda m: m["files"][0].__setitem__("format", "PDF"),
            lambda m: m["files"][0].__setitem__("rel_path", "bench/vision/synthetic/other.png"),
        ],
    )
    def test_tampered_entry_fields_blocked(self, repo: dict, mutator):
        write_manifest(repo, _mutate(load_manifest(repo), mutator))
        assert_no_runner(lambda: validate_synthetic_gate([repo["png"]]), VisionBlockedError)

    def test_uppercase_sha256_same_digest_is_case_insensitive_not_tamper(self, repo: dict):
        """sha256 hex là case-insensitive: uppercase của ĐÚNG digest vẫn qua cổng.

        Không nới gate: giá trị hash không đổi, file trên đĩa vẫn phải khớp cả
        manifest lẫn pinned registry. Digest KHÁC (vd ``'0' * 64``) vẫn bị chặn
        trong ``test_tampered_entry_fields_blocked``.
        """
        write_manifest(
            repo,
            _mutate(
                load_manifest(repo),
                lambda m: m["files"][0].__setitem__("sha256", PNG_SHA.upper()),
            ),
        )

        result = validate_synthetic_gate([repo["png"]])
        assert len(result) == 1
        assert result[0].mime_type == "image/png"

    def test_duplicate_manifest_entry_blocked(self, repo: dict):
        def duplicate(manifest: dict) -> None:
            manifest["files"].append(dict(manifest["files"][0]))

        write_manifest(repo, _mutate(load_manifest(repo), duplicate))
        assert_no_runner(lambda: validate_synthetic_gate([repo["png"]]), VisionBlockedError)

    def test_unknown_file_declared_blocked(self, repo: dict):
        def add_unknown(manifest: dict) -> None:
            manifest["files"].append(
                {
                    "path": "not_generated.png",
                    "sha256": "a" * 64,
                    "bytes": 10,
                    "format": "PNG",
                }
            )

        write_manifest(repo, _mutate(load_manifest(repo), add_unknown))
        assert_no_runner(lambda: validate_synthetic_gate([repo["png"]]), VisionBlockedError)

    def test_manifest_omitting_requested_file_blocked(self, repo: dict):
        """Manifest hợp lệ nhưng không khai file được yêu cầu -> chặn (danh sách đóng)."""

        def drop_png(manifest: dict) -> None:
            manifest["files"] = [e for e in manifest["files"] if e["path"] != "page_a.png"]

        write_manifest(repo, _mutate(load_manifest(repo), drop_png))
        assert_no_runner(lambda: validate_synthetic_gate([repo["png"]]), VisionBlockedError)

    def test_missing_manifest_blocked(self, repo: dict):
        (repo["synth"] / "manifest.json").unlink()
        assert_no_runner(lambda: validate_synthetic_gate([repo["png"]]), VisionBlockedError)

    def test_file_content_modified_on_disk_blocked(self, repo: dict):
        repo["png"].write_bytes(PNG_MAGIC + b"tampered bytes")
        with pytest.raises(VisionBlockedError, match="sha256 mismatch|size mismatch"):
            validate_synthetic_gate([repo["png"]])

    def test_file_truncated_on_disk_blocked(self, repo: dict):
        repo["png"].write_bytes(PNG_MAGIC)
        with pytest.raises(VisionBlockedError):
            validate_synthetic_gate([repo["png"]])


# ---------------------------------------------------------------------------
# 4. Symlink & path boundary
# ---------------------------------------------------------------------------

class TestSymlinkAndBoundaries:
    def test_file_symlink_blocked(self, repo: dict):
        link = repo["synth"] / "link_page.png"
        try:
            link.symlink_to(repo["png"])
        except OSError:
            pytest.skip("Filesystem does not support symlinks")
        with pytest.raises(VisionSecurityError, match="Symlink detected"):
            validate_synthetic_gate([link])

    def test_manifest_symlink_blocked(self, repo: dict, tmp_path: Path):
        manifest = repo["synth"] / "manifest.json"
        backup = tmp_path / "manifest_copy.json"
        backup.write_bytes(manifest.read_bytes())
        manifest.unlink()
        try:
            manifest.symlink_to(backup)
        except OSError:
            pytest.skip("Filesystem does not support symlinks")
        with pytest.raises(VisionSecurityError, match="Symlink detected"):
            validate_synthetic_gate([repo["png"]])

    def test_symlink_ancestor_directory_blocked(self, repo: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        fake_root = (tmp_path / "fake_repo").resolve()
        fake_root.mkdir()
        try:
            (fake_root / "bench").symlink_to(repo["root"] / "bench", target_is_directory=True)
        except OSError:
            pytest.skip("Filesystem does not support symlinks")
        monkeypatch.setattr(vision, "REAL_REPO_ROOT", fake_root)

        with pytest.raises(VisionSecurityError, match="Symlink detected"):
            validate_synthetic_gate([fake_root / "bench" / "vision" / "synthetic" / "page_a.png"])

    def test_absolute_path_outside_repo_blocked(self, repo: dict, tmp_path: Path):
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_file = outside / "page_a.png"
        outside_file.write_bytes(PNG_PAYLOAD)
        with pytest.raises(VisionSecurityError, match="outside fixed synthetic directory"):
            validate_synthetic_gate([outside_file])

    def test_path_inside_repo_but_outside_synthetic_dir_blocked(self, repo: dict):
        sibling = repo["root"] / "bench" / "vision" / "source_page.png"
        sibling.write_bytes(PNG_PAYLOAD)
        with pytest.raises(VisionSecurityError, match="outside fixed synthetic directory"):
            validate_synthetic_gate([sibling])

    def test_nested_relative_path_blocked(self, repo: dict):
        nested = repo["synth"] / "sub" / "page_a.png"
        nested.parent.mkdir()
        nested.write_bytes(PNG_PAYLOAD)
        with pytest.raises(VisionSecurityError):
            validate_synthetic_gate(["sub/page_a.png"])

    def test_traversal_blocked(self, repo: dict):
        with pytest.raises(VisionSecurityError, match="Path traversal"):
            validate_synthetic_gate([repo["synth"] / ".." / "page_a.png"])

    def test_duplicate_attachment_blocked(self, repo: dict):
        with pytest.raises(VisionBlockedError, match="Duplicate attachment"):
            validate_synthetic_gate([repo["png"], repo["png"]])

    def test_empty_attachment_list_blocked(self):
        with pytest.raises(VisionFormatError, match="No attachment files"):
            validate_synthetic_gate([])


# ---------------------------------------------------------------------------
# 5. Policy blocks trước probe/spawn (runner = 0)
# ---------------------------------------------------------------------------

class TestPolicyBlocksBeforeProbe:
    def test_real_data_without_synthetic_flag_blocked_before_io(self, repo: dict):
        assert_blocked_before_io(
            lambda: check_vision_gate(
                files=[repo["png"]], model=DEEPSEEK, adapter=OPENCODE, is_synthetic=False
            ),
            VisionBlockedError,
        )

    def test_allow_sensitive_blocked_even_without_files(self):
        assert_blocked_before_io(
            lambda: check_vision_gate(files=[], model=DEEPSEEK, allow_sensitive=True),
            VisionBlockedError,
        )

    def test_confirmation_string_blocked_even_without_files(self):
        assert_blocked_before_io(
            lambda: check_vision_gate(files=[], model=DEEPSEEK, confirmation="Tuan approved"),
            VisionBlockedError,
        )

    @pytest.mark.parametrize("adapter", ["hermes", "codex", "agy", "gemini", "grok", "random_adapter", "", "   "])
    def test_unknown_or_blank_adapter_blocked_before_io(self, repo: dict, adapter: str):
        assert_blocked_before_io(
            lambda: check_vision_gate(
                files=[repo["png"]], model=DEEPSEEK, adapter=adapter, is_synthetic=True
            ),
            VisionBlockedError,
        )

    @pytest.mark.parametrize(
        "model,pre_gate_blocked",
        [
            # Model chưa có trong metadata / contributor: chặn ngay tại capability
            # check, tức TRƯỚC mọi file I/O.
            ("unknown-model", True),
            ("gpt-6.1-sol", True),
            ("deepseek-v4.1-flash-contributor", True),
            # glm-5.3 là model tin cậy nhưng image=false, pdf=false: mismatch chỉ
            # phát hiện được SAU khi đọc manifest + magic bytes, nên chỉ assert runner=0.
            ("glm-5.3", False),
        ],
    )
    def test_untrusted_or_non_vision_model_blocked_before_io(
        self, repo: dict, model: str, pre_gate_blocked: bool
    ):
        """Model lạ / contributor bị chặn trước I/O; model thiếu capability vẫn bị chặn."""
        call = lambda: check_vision_gate(
            files=[repo["png"]], model=model, adapter=OPENCODE, is_synthetic=True
        )
        if pre_gate_blocked:
            assert_blocked_before_io(call, VisionBlockedError)
        else:
            assert_no_runner(call, VisionBlockedError)

    def test_outside_path_blocked_without_runner(self, repo: dict, tmp_path: Path):
        """Path ngoài synthetic dir vẫn bị chặn; validation cần I/O nên chỉ assert runner=0."""
        outside = tmp_path / "elsewhere.png"
        outside.write_bytes(PNG_PAYLOAD)
        assert_no_runner(
            lambda: check_vision_gate(
                files=[outside], model=DEEPSEEK, adapter=OPENCODE, is_synthetic=True
            ),
            VisionSecurityError,
        )


# ---------------------------------------------------------------------------
# 6. Không có builder/bypass public
# ---------------------------------------------------------------------------

class TestNoPublicBypass:
    def test_public_convert_pdf_blocked_before_io(self, repo: dict, tmp_path: Path):
        with patch("subprocess.run") as mock_run, \
             patch("shutil.which") as mock_which, \
             patch("builtins.open") as mock_open:
            with pytest.raises(VisionBlockedError, match="blocked fail-closed"):
                convert_pdf_to_images(
                    pdf_path=repo["pdf"],
                    output_dir=tmp_path / "out",
                    pdftoppm_bin="/tmp/evil",
                )
            mock_run.assert_not_called()
            mock_which.assert_not_called()
            mock_open.assert_not_called()

    @pytest.mark.parametrize(
        "func,extra",
        [
            (check_vision_gate, {"files": ["page_a.png"], "model": DEEPSEEK, "adapter": OPENCODE}),
            (prepare_vision_input, {"files": ["page_a.png"], "model": DEEPSEEK, "adapter": OPENCODE}),
            (validate_synthetic_gate, {"files": ["page_a.png"]}),
        ],
    )
    def test_no_repo_root_parameter(self, func, extra):
        with pytest.raises(TypeError):
            func(repo_root=Path("/tmp/fake"), **extra)  # type: ignore[call-arg]

    def test_no_verified_adapters_parameter(self, repo: dict):
        with pytest.raises(TypeError):
            check_vision_gate(
                files=[repo["png"]],
                model=DEEPSEEK,
                adapter=OPENCODE,
                is_synthetic=True,
                verified_adapters={OPENCODE},  # type: ignore[call-arg]
            )

    def test_prepare_blocks_arbitrary_attachment(self, repo: dict, tmp_path: Path):
        rogue = tmp_path / "rogue_page.png"
        rogue.write_bytes(PNG_PAYLOAD)
        with pytest.raises(VisionBlockedError):
            prepare_vision_input(
                files=[rogue], model=DEEPSEEK, adapter=OPENCODE, is_synthetic=True
            )

    def test_prepare_hermes_still_blocked(self, repo: dict):
        with pytest.raises(VisionBlockedError, match="not verified"):
            prepare_vision_input(
                files=[repo["png"]], model=DEEPSEEK, adapter="hermes", is_synthetic=True
            )


# ---------------------------------------------------------------------------
# 7. DeepSeek split trusted PDF qua prepare hiện có
# ---------------------------------------------------------------------------

class TestTrustedPdfSplit:
    def test_deepseek_splits_actual_repo_pdf(self, tmp_path: Path):
        actual = vision.REAL_REPO_ROOT / "bench" / "vision" / "synthetic" / "multipage_contract.pdf"
        assert actual.is_file()

        # Output luôn nằm trong private TMPDIR do helper tự tạo; folder caller
        # không còn là đầu ra nên `output_dir` không được truyền vào nữa.
        written_dirs: list[Path] = []

        def fake_run(cmd, **kwargs):
            out_prefix = Path(cmd[-1])
            written_dirs.append(out_prefix.parent)
            for n in (1, 2):
                (out_prefix.parent / f"{out_prefix.name}-{n}.png").write_bytes(
                    PNG_MAGIC + f"page {n}".encode()
                )
            return MagicMock(returncode=0)

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_run) as mock_run:
            result = prepare_vision_input(
                files=[actual],
                model=DEEPSEEK,
                adapter=OPENCODE,
                is_synthetic=True,
            )

        assert [p.name for p in result] == [
            "multipage_contract-1.png",
            "multipage_contract-2.png",
        ]
        # Mọi page nằm trong đúng một private dir mới, KHÔNG nằm trong repo.
        assert len(written_dirs) == 1
        conv_dir = written_dirs[0]
        assert conv_dir.name.startswith("polykit-vision-")
        assert {p.parent for p in result} == {conv_dir}
        assert vision.REAL_REPO_ROOT not in conv_dir.parents
        for p in result:
            assert p.is_file() and not p.is_symlink()

        cmd = mock_run.call_args[0][0]
        assert isinstance(cmd, list) and "-png" in cmd and "shell" not in mock_run.call_args[1]

    def test_deepseek_split_rejects_caller_output_dir(self):
        """`output_dir` của caller bị reject fail-closed, không copy page ra đó."""
        actual = vision.REAL_REPO_ROOT / "bench" / "vision" / "synthetic" / "multipage_contract.pdf"
        with patch("subprocess.run") as mock_run:
            with pytest.raises(VisionBlockedError, match="output_dir is rejected fail-closed"):
                prepare_vision_input(
                    files=[actual],
                    model=DEEPSEEK,
                    adapter=OPENCODE,
                    is_synthetic=True,
                    output_dir=actual.parent,
                )
        mock_run.assert_not_called()

    def test_glm_keeps_trusted_pdf_direct(self):
        actual = vision.REAL_REPO_ROOT / "bench" / "vision" / "synthetic" / "multipage_contract.pdf"
        with patch("subprocess.run") as mock_run:
            result = prepare_vision_input(
                files=[actual], model=GLM, adapter=OPENCODE, is_synthetic=True
            )
        mock_run.assert_not_called()
        assert result == [actual.resolve()]


# ---------------------------------------------------------------------------
# 8. Không log nội dung/PII
# ---------------------------------------------------------------------------

def test_error_messages_do_not_leak_file_content(repo: dict, capsys):
    repo["png"].write_bytes(PNG_MAGIC + b"SECRET-BANK-ACCOUNT-123456789")
    with pytest.raises(VisionBlockedError) as exc_info:
        validate_synthetic_gate([repo["png"]])
    captured = capsys.readouterr()
    assert "SECRET-BANK-ACCOUNT" not in str(exc_info.value)
    assert "SECRET-BANK-ACCOUNT" not in captured.out + captured.err
