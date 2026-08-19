"""BUG-2 (18/08/2026): prompt dài không đi qua stdin được — quoting/xuống dòng/dấu
tiếng Việt vỡ ở tầng shell. --prompt-file là đường truyền thay thế."""
import subprocess, sys
from pathlib import Path

DISPATCH = Path(__file__).resolve().parents[1] / "bin" / "dispatch.py"


def _run(args, stdin=""):
    return subprocess.run([sys.executable, str(DISPATCH), *args],
                          input=stdin, capture_output=True, text=True, timeout=60)


def test_prompt_file_khong_ton_tai_bi_chan(tmp_path):
    r = _run(["dsh", "--prompt-file", str(tmp_path / "khong-co.txt"), "--result-json"])
    assert r.returncode == 2
    assert "không đọc được --prompt-file" in r.stderr


def test_prompt_file_rong_bi_chan(tmp_path):
    f = tmp_path / "rong.txt"; f.write_text("   \n", encoding="utf-8")
    r = _run(["dsh", "--prompt-file", str(f), "--result-json"])
    assert r.returncode == 2
    assert "rỗng" in r.stderr


def test_prompt_file_giu_nguyen_dau_tieng_viet_va_xuong_dong(tmp_path):
    """Nội dung nhiều dòng + dấu phải tới nguyên vẹn — đây chính là ca stdin làm hỏng."""
    noi_dung = 'Soát hồ sơ: "số tiền" 450 vs 300\nDòng hai — lãi suất 9,9%\n'
    f = tmp_path / "prompt.txt"; f.write_text(noi_dung, encoding="utf-8")
    assert f.read_text(encoding="utf-8") == noi_dung
    r = _run(["dsh", "--prompt-file", str(f), "--dump-config"])
    assert r.returncode == 0
