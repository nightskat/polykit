"""PR#2 phát hiện: `_convert_pdf_to_images` kiểm thiếu pdftoppm TRƯỚC gate an ninh
(output_dir caller, symlink nguồn) ⇒ máy không có pdftoppm thì gate không chạy, lỗi
trả về che mất vi phạm thật. Gate phải chạy trước, độc lập với máy có binary hay không."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from lib.vision import (  # noqa: E402
    VisionBlockedError, VisionSecurityError, _convert_pdf_to_images,
)


def _pdf(p: Path) -> Path:
    p.write_bytes(b"%PDF-1.4\n%fake\n")
    return p


def test_output_dir_bi_chan_du_khong_co_pdftoppm(tmp_path):
    pdf = _pdf(tmp_path / "a.pdf")
    with patch("shutil.which", return_value=None):
        with pytest.raises(VisionBlockedError, match="output_dir"):
            _convert_pdf_to_images(pdf, output_dir=tmp_path / "out")


def test_symlink_bi_chan_du_khong_co_pdftoppm(tmp_path):
    pdf = _pdf(tmp_path / "a.pdf")
    link = tmp_path / "l.pdf"
    try:
        link.symlink_to(pdf)
    except OSError:
        pytest.skip("OS không cho tạo symlink (Windows không quyền)")
    with patch("shutil.which", return_value=None):
        with pytest.raises(VisionSecurityError):
            _convert_pdf_to_images(link)


def test_thieu_pdftoppm_van_blocked_khi_gate_qua(tmp_path):
    pdf = _pdf(tmp_path / "a.pdf")
    with patch("shutil.which", return_value=None):
        with pytest.raises(VisionBlockedError, match="pdftoppm binary not found"):
            _convert_pdf_to_images(pdf)
