"""Regression: cô lập thư mục output của PDF conversion (finding stale-glob).

Bối cảnh finding: ``prepare_vision_input`` nhận ``output_dir`` của caller rồi
chuyển thẳng cho ``_convert_pdf_to_images``, helper này glob ``<prefix>-*.png``
trong đúng thư mục đó. Nguồn PDF đã qua cổng synthetic nhưng thư mục caller thì
KHÔNG: một ``multipage_contract-99.png`` cũ hay symlink trỏ ra ngoài nằm sẵn ở
đó sẽ được trả về như thể do pdftoppm sinh ra.

Nguyên tắc được kiểm ở đây:
1. Folder caller không bao giờ được dùng làm output: ``output_dir`` bị reject
   fail-closed, không subprocess, không mkdtemp dưới đó.
2. Mỗi conversion nhận private dir MỚI trong TMPDIR; stale ``<prefix>-99.png``
   và symlink đặt sẵn ở folder caller KHÔNG BAO GIỜ xuất hiện trong kết quả.
3. Không glob: entry lạ / symlink / non-regular / rỗng / không phải PNG trong
   dir conversion ⇒ VisionConversionError (fail-closed), không bỏ qua im lặng.
4. Page id phải liên tục 1..N (chấp nhận zero-pad của poppler), N và bytes có trần.
5. Concurrent conversions dùng dir khác nhau, không lẫn trang.
6. Source bị cổng chặn ⇒ không conversion nào chạy (mkdtemp = 0, subprocess = 0).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import bin.lib.vision as vision
from bin.lib.vision import (
    EXPECTED_MANIFEST_GENERATOR,
    EXPECTED_MANIFEST_SCHEMA_VERSION,
    MAX_CONVERSION_PAGES,
    PDF_MAGIC,
    PNG_MAGIC,
    VisionBlockedError,
    VisionConversionError,
    _convert_pdf_to_images,
    prepare_vision_input,
)

DEEPSEEK = "deepseek-v4.1-flash"
OPENCODE = "opencode"

PDF_PAYLOAD = PDF_MAGIC + b"-1.7\npolykit-vision-isolation-fixture\n"
PDF_SHA = hashlib.sha256(PDF_PAYLOAD).hexdigest()
PNG_PAGE_PAYLOAD = PNG_MAGIC + b"polykit-isolation-page-bytes"

# Tên PDF khớp prefix mong đợi của page output (stem = "isolation_doc").
PDF_NAME = "isolation_doc.pdf"
PAGE_PREFIX = "isolation_doc"


# ---------------------------------------------------------------------------
# Fixture repo synthetic (chỉ PDF) + helper giả lập pdftoppm
# ---------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    root = (tmp_path / "repo").resolve()
    synth = root / "bench" / "vision" / "synthetic"
    synth.mkdir(parents=True)

    pdf = synth / PDF_NAME
    pdf.write_bytes(PDF_PAYLOAD)

    registry = {
        PDF_NAME: {
            "sha256": PDF_SHA,
            "bytes": len(PDF_PAYLOAD),
            "format": "PDF",
            "rel_path": f"bench/vision/synthetic/{PDF_NAME}",
        },
    }
    manifest = {
        "schema_version": EXPECTED_MANIFEST_SCHEMA_VERSION,
        "generator": EXPECTED_MANIFEST_GENERATOR,
        "files": [
            {
                "path": name,
                "rel_path": rec["rel_path"],
                "format": rec["format"],
                "bytes": rec["bytes"],
                "sha256": rec["sha256"],
            }
            for name, rec in registry.items()
        ],
    }
    (synth / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(vision, "REAL_REPO_ROOT", root)
    monkeypatch.setattr(vision, "TRUSTED_SYNTHETIC_REGISTRY", registry)

    return {"root": root, "synth": synth, "pdf": pdf, "registry": registry}


def fake_pdftoppm(
    pages: int = 2,
    pad: int = 0,
    payload: bytes = PNG_PAGE_PAYLOAD,
    extra=None,
):
    """Giả lập pdftoppm: ghi ``<prefix>-<n>.png`` vào ĐÚNG out_prefix trong argv.

    ``extra(dir, prefix)`` cho phép chèn file lạ/symlink để test fail-closed.
    """

    def _run(cmd, **kwargs):
        out_prefix = Path(cmd[-1])
        out_dir = out_prefix.parent
        for n in range(1, pages + 1):
            num = f"{n:0{pad}d}" if pad else str(n)
            (out_dir / f"{out_prefix.name}-{num}.png").write_bytes(payload)
        if extra is not None:
            extra(out_dir, out_prefix.name)
        return MagicMock(returncode=0)

    return _run


def page_names(paths) -> list[str]:
    return [Path(p).name for p in paths]


def assert_outside_caller(paths, caller_dir: Path) -> None:
    """Không path nào được nằm trong folder caller (chỉ TMPDIR private)."""
    resolved_caller = caller_dir.resolve()
    for p in paths:
        resolved = Path(p).resolve()
        assert not str(resolved).startswith(str(resolved_caller) + os.sep), (
            f"page trả về nằm trong folder caller: {resolved}"
        )
        assert not resolved.is_symlink()


def make_caller_dir(tmp_path: Path) -> Path:
    """Folder caller 'bẩn': có sẵn page cùng prefix + symlink trỏ ra ngoài."""
    caller = tmp_path / "caller_out"
    caller.mkdir()
    (caller / f"{PAGE_PREFIX}-99.png").write_bytes(PNG_PAGE_PAYLOAD)
    try:
        (caller / f"{PAGE_PREFIX}-100.png").symlink_to("/etc/hosts")
    except OSError:
        pytest.skip("Filesystem does not support symlinks")
    return caller


def snapshot(directory: Path) -> set[str]:
    return {p.name for p in directory.iterdir()}


# ---------------------------------------------------------------------------
# 1. output_dir của caller bị reject fail-closed
# ---------------------------------------------------------------------------

class TestCallerOutputDirRejected:
    def test_prepare_rejects_caller_output_dir_fail_closed(self, repo: dict, tmp_path: Path):
        caller = make_caller_dir(tmp_path)
        before = snapshot(caller)

        with patch("subprocess.run") as mock_run, \
             patch("tempfile.mkdtemp") as mock_mkdtemp, \
             patch("shutil.which", return_value="/usr/bin/pdftoppm"):
            with pytest.raises(VisionBlockedError, match="output_dir is rejected fail-closed"):
                prepare_vision_input(
                    files=[repo["pdf"]],
                    model=DEEPSEEK,
                    adapter=OPENCODE,
                    is_synthetic=True,
                    output_dir=caller,
                )

        mock_run.assert_not_called()
        mock_mkdtemp.assert_not_called()
        assert snapshot(caller) == before, "folder caller bị đụng vào"

    def test_helper_rejects_caller_output_dir(self, repo: dict, tmp_path: Path):
        caller = make_caller_dir(tmp_path)
        before = snapshot(caller)

        with patch("subprocess.run") as mock_run:
            with pytest.raises(VisionBlockedError, match="output_dir is rejected fail-closed"):
                _convert_pdf_to_images(pdf_path=repo["pdf"], output_dir=caller)

        mock_run.assert_not_called()
        assert snapshot(caller) == before

    def test_caller_output_dir_nested_inside_repo_still_rejected(self, repo: dict):
        """Kể cả output_dir nằm trong repo synthetic vẫn bị reject (không re-gate)."""
        nested = repo["synth"] / "pages"
        nested.mkdir()
        with patch("subprocess.run") as mock_run:
            with pytest.raises(VisionBlockedError, match="output_dir is rejected fail-closed"):
                prepare_vision_input(
                    files=[repo["pdf"]],
                    model=DEEPSEEK,
                    adapter=OPENCODE,
                    is_synthetic=True,
                    output_dir=nested,
                )
        mock_run.assert_not_called()

    def test_gate_block_wins_over_output_dir_and_no_conversion(self, repo: dict, tmp_path: Path):
        """Source bị cổng chặn: lỗi gate thắng, không mkdtemp, không subprocess."""
        rogue = tmp_path / "rogue.pdf"
        rogue.write_bytes(PDF_PAYLOAD)

        with patch("subprocess.run") as mock_run, \
             patch("tempfile.mkdtemp") as mock_mkdtemp, \
             patch("shutil.which") as mock_which:
            with pytest.raises(VisionBlockedError):
                prepare_vision_input(
                    files=[rogue],
                    model=DEEPSEEK,
                    adapter=OPENCODE,
                    is_synthetic=True,
                    output_dir=tmp_path / "out",
                )

        mock_run.assert_not_called()
        mock_mkdtemp.assert_not_called()
        mock_which.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Stale file / symlink trong folder caller không bao giờ được trả về
# ---------------------------------------------------------------------------

class TestStaleFilesNeverReturned:
    def test_stale_prefix_pages_and_symlink_in_caller_dir_never_returned(
        self, repo: dict, tmp_path: Path
    ):
        caller = make_caller_dir(tmp_path)
        stale_page = caller / f"{PAGE_PREFIX}-99.png"
        stale_link = caller / f"{PAGE_PREFIX}-100.png"

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=2)):
            result = prepare_vision_input(
                files=[repo["pdf"]],
                model=DEEPSEEK,
                adapter=OPENCODE,
                is_synthetic=True,
            )

        assert page_names(result) == [f"{PAGE_PREFIX}-1.png", f"{PAGE_PREFIX}-2.png"]
        assert_outside_caller(result, caller)
        assert stale_page.exists(), "file cũ của caller phải còn nguyên (không bị xoá/sửa)"
        assert stale_link.is_symlink()
        for p in result:
            assert Path(p).resolve() != stale_page.resolve()

    def test_stale_pages_in_cwd_not_picked_up(self, repo: dict, tmp_path: Path, monkeypatch):
        """File cùng prefix nằm ở CWD cũng không được lấy (không glob ngoài TMPDIR)."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        stale = cwd / f"{PAGE_PREFIX}-1.png"
        stale.write_bytes(PNG_PAGE_PAYLOAD)
        monkeypatch.chdir(cwd)

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=1)):
            result = prepare_vision_input(
                files=[repo["pdf"]],
                model=DEEPSEEK,
                adapter=OPENCODE,
                is_synthetic=True,
            )

        assert len(result) == 1
        assert Path(result[0]).resolve() != stale.resolve()
        assert_outside_caller(result, cwd)

    def test_conversion_dir_is_fresh_private_tempdir(self, repo: dict):
        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=2)):
            result = prepare_vision_input(
                files=[repo["pdf"]],
                model=DEEPSEEK,
                adapter=OPENCODE,
                is_synthetic=True,
            )

        temp_root = Path(tempfile.gettempdir()).resolve()
        parents = {Path(p).parent for p in result}
        assert len(parents) == 1
        parent = parents.pop()
        assert parent.is_dir()
        assert not parent.is_symlink()
        assert parent.name.startswith("polykit-vision-")
        assert parent.parent.resolve() == temp_root
        assert repo["root"] not in parent.parents
        for p in result:
            assert Path(p).is_absolute()
            assert Path(p).is_file()
            assert not Path(p).is_symlink()

    def test_each_conversion_gets_distinct_dir(self, repo: dict):
        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=1)):
            first = _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)
            second = _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)

        assert first[0].parent != second[0].parent


# ---------------------------------------------------------------------------
# 3. Không glob: validate từng entry output
# ---------------------------------------------------------------------------

class TestStrictOutputValidation:
    def test_no_output_refused(self, repo: dict):
        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=0)):
            with pytest.raises(VisionConversionError, match="produced no image pages"):
                _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)

    def test_unexpected_extra_entry_refused(self, repo: dict):
        def extra(out_dir: Path, prefix: str) -> None:
            (out_dir / "evil-99.png").write_bytes(PNG_PAGE_PAYLOAD)

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=1, extra=extra)):
            with pytest.raises(VisionConversionError, match="Unexpected entry"):
                _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)

    def test_symlink_page_refused(self, repo: dict):
        def extra(out_dir: Path, prefix: str) -> None:
            try:
                (out_dir / f"{prefix}-1.png").symlink_to("/etc/hosts")
            except OSError:
                pytest.skip("Filesystem does not support symlinks")

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=0, extra=extra)):
            with pytest.raises(VisionConversionError, match="regular non-symlink"):
                _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)

    def test_directory_entry_refused(self, repo: dict):
        def extra(out_dir: Path, prefix: str) -> None:
            (out_dir / f"{prefix}-1.png").mkdir()

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=0, extra=extra)):
            with pytest.raises(VisionConversionError, match="regular"):
                _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)

    def test_empty_page_refused(self, repo: dict):
        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=1, payload=b"")):
            with pytest.raises(VisionConversionError, match="empty page image"):
                _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)

    def test_non_png_page_refused(self, repo: dict):
        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=1, payload=b"\xff\xd8\xffnot-a-png")):
            with pytest.raises(VisionConversionError, match="not a PNG"):
                _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)

    def test_non_contiguous_page_ids_refused(self, repo: dict):
        def extra(out_dir: Path, prefix: str) -> None:
            (out_dir / f"{prefix}-3.png").write_bytes(PNG_PAGE_PAYLOAD)

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=1, extra=extra)):
            with pytest.raises(VisionConversionError, match="not contiguous"):
                _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)

    def test_missing_page_one_refused(self, repo: dict):
        def extra(out_dir: Path, prefix: str) -> None:
            (out_dir / f"{prefix}-2.png").write_bytes(PNG_PAGE_PAYLOAD)

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=0, extra=extra)):
            with pytest.raises(VisionConversionError, match="not contiguous"):
                _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)

    def test_too_many_pages_refused(self, repo: dict):
        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=MAX_CONVERSION_PAGES + 1)):
            with pytest.raises(VisionConversionError, match="more than"):
                _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)

    def test_page_over_byte_cap_refused(self, repo: dict, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(vision, "MAX_CONVERSION_PAGE_BYTES", 64)
        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=1, payload=PNG_MAGIC + b"x" * 200)):
            with pytest.raises(VisionConversionError, match="maximum page size"):
                _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)

    def test_total_byte_cap_refused(self, repo: dict, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(vision, "MAX_CONVERSION_TOTAL_BYTES", 16)
        payload = PNG_MAGIC + b"y" * 32
        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=2, payload=payload)):
            with pytest.raises(VisionConversionError, match="total size"):
                _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)


# ---------------------------------------------------------------------------
# 4. Thứ tự trang & zero-pad của poppler
# ---------------------------------------------------------------------------

class TestPageOrdering:
    def test_numeric_order_not_lexicographic(self, repo: dict):
        def extra(out_dir: Path, prefix: str) -> None:
            # Ghi thêm trang 10, 11 để đủ dãy liên tục 1..11 (page id phải contiguous).
            for n in (10, 11):
                (out_dir / f"{prefix}-{n}.png").write_bytes(PNG_PAGE_PAYLOAD)

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=9, extra=extra)):
            result = _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)

        names = page_names(result)
        assert names == [f"{PAGE_PREFIX}-{n}.png" for n in range(1, 12)]
        # Không xếp theo bảng chữ cái (page-10 trước page-2).
        assert names.index(f"{PAGE_PREFIX}-2.png") < names.index(f"{PAGE_PREFIX}-10.png")

    def test_zero_padded_contiguous_pages_accepted(self, repo: dict):
        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=3, pad=2)):
            result = _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)

        assert page_names(result) == [
            f"{PAGE_PREFIX}-01.png",
            f"{PAGE_PREFIX}-02.png",
            f"{PAGE_PREFIX}-03.png",
        ]

    def test_prefix_sanitized_for_unsafe_stem(self, repo: dict):
        """Prefix có ký tự lạ vẫn tạo tên file an toàn, không path traversal."""
        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=1)):
            result = _convert_pdf_to_images(
                pdf_path=repo["pdf"], prefix="../../etc/pass wd"
            )

        assert len(result) == 1
        name = result[0].name
        assert "/" not in name and "\\" not in name and ".." not in name
        assert result[0].parent.name.startswith("polykit-vision-")


# ---------------------------------------------------------------------------
# 5. Concurrent conversions
# ---------------------------------------------------------------------------

class TestConcurrentConversions:
    def test_concurrent_conversions_use_distinct_dirs(self, repo: dict):
        results: list[list[Path]] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(4)

        def worker() -> None:
            try:
                barrier.wait(timeout=10)
                results.append(
                    _convert_pdf_to_images(pdf_path=repo["pdf"], prefix=PAGE_PREFIX)
                )
            except BaseException as exc:  # pragma: no cover - chỉ để lộ lỗi thread
                errors.append(exc)

        # Patch MỘT lần ngoài thread: patch() không thread-safe, start/stop trong
        # nhiều thread sẽ để lại subprocess.run bị mock cho test sau.
        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=3)):
            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

        assert not errors, errors
        assert len(results) == 4
        parents = {pages[0].parent for pages in results}
        assert len(parents) == 4, "concurrent conversions phải dùng dir riêng"
        for pages in results:
            assert page_names(pages) == [
                f"{PAGE_PREFIX}-1.png",
                f"{PAGE_PREFIX}-2.png",
                f"{PAGE_PREFIX}-3.png",
            ]
            assert {p.parent for p in pages} == {pages[0].parent}

    def test_concurrent_prepare_isolated(self, repo: dict):
        results: list[list[Path]] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(2)

        def worker() -> None:
            try:
                barrier.wait(timeout=10)
                results.append(
                    prepare_vision_input(
                        files=[repo["pdf"]],
                        model=DEEPSEEK,
                        adapter=OPENCODE,
                        is_synthetic=True,
                    )
                )
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        with patch("shutil.which", return_value="/usr/bin/pdftoppm"), \
             patch("subprocess.run", side_effect=fake_pdftoppm(pages=2)):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

        assert not errors, errors
        assert len({pages[0].parent for pages in results}) == 2


# ---------------------------------------------------------------------------
# 6. Source gate chặn ⇒ không conversion
# ---------------------------------------------------------------------------

class TestSourceGateBlocksConversion:
    def test_sensitive_flag_blocks_before_any_conversion(self, repo: dict):
        with patch("tempfile.mkdtemp") as mock_mkdtemp, \
             patch("subprocess.run") as mock_run, \
             patch("shutil.which") as mock_which:
            with pytest.raises(VisionBlockedError):
                prepare_vision_input(
                    files=[repo["pdf"]],
                    model=DEEPSEEK,
                    adapter=OPENCODE,
                    is_synthetic=False,
                )
        mock_mkdtemp.assert_not_called()
        mock_run.assert_not_called()
        mock_which.assert_not_called()

    def test_image_attachment_creates_no_conversion_dir(self, repo: dict, tmp_path: Path):
        """PNG đi thẳng: không mkdtemp, không subprocess (giữ nguyên hành vi cũ)."""
        png = repo["synth"] / "page_direct.png"
        payload = PNG_MAGIC + b"direct-png"
        png.write_bytes(payload)
        sha = hashlib.sha256(payload).hexdigest()
        registry = dict(repo["registry"])
        registry["page_direct.png"] = {
            "sha256": sha,
            "bytes": len(payload),
            "format": "PNG",
            "rel_path": "bench/vision/synthetic/page_direct.png",
        }
        manifest = json.loads((repo["synth"] / "manifest.json").read_text(encoding="utf-8"))
        manifest["files"].append(
            {
                "path": "page_direct.png",
                "rel_path": "bench/vision/synthetic/page_direct.png",
                "format": "PNG",
                "bytes": len(payload),
                "sha256": sha,
            }
        )
        (repo["synth"] / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        with patch.object(vision, "TRUSTED_SYNTHETIC_REGISTRY", registry), \
             patch("tempfile.mkdtemp") as mock_mkdtemp, \
             patch("subprocess.run") as mock_run:
            result = prepare_vision_input(
                files=[png],
                model=DEEPSEEK,
                adapter=OPENCODE,
                is_synthetic=True,
            )

        mock_mkdtemp.assert_not_called()
        mock_run.assert_not_called()
        assert result == [png.resolve()]

    def test_glm_pdf_direct_no_conversion(self, repo: dict):
        with patch("tempfile.mkdtemp") as mock_mkdtemp, \
             patch("subprocess.run") as mock_run:
            result = prepare_vision_input(
                files=[repo["pdf"]],
                model="glm-5.3-flash",
                adapter=OPENCODE,
                is_synthetic=True,
            )
        mock_mkdtemp.assert_not_called()
        mock_run.assert_not_called()
        assert result == [repo["pdf"].resolve()]

    def test_source_pdf_symlink_blocked(self, repo: dict, tmp_path: Path):
        link = tmp_path / "link_doc.pdf"
        try:
            link.symlink_to(repo["pdf"])
        except OSError:
            pytest.skip("Filesystem does not support symlinks")
        with patch("subprocess.run") as mock_run:
            with pytest.raises(vision.VisionError, match="Symlink"):
                _convert_pdf_to_images(pdf_path=link)
        mock_run.assert_not_called()
