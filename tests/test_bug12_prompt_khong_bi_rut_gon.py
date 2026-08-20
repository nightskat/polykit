"""BUG-12 (20/08/2026): `--prompt "văn bản"` lặng lẽ biến thành `--prompt-file`.

argparse mặc định cho rút gọn tiền tố. Từ lúc thêm `--prompt-file` (19/08),
`--prompt` trở thành tiền tố duy nhất khớp nó → câu chữ bị coi là ĐƯỜNG DẪN.
Lệnh cũ đang chạy tốt bỗng gãy, và thông báo lỗi nói về file — sai chỗ để đi tìm.
"""
import json
import subprocess
import sys
from pathlib import Path

DISPATCH = Path(__file__).resolve().parents[1] / "bin" / "dispatch.py"


def _chay(args, stdin=""):
    return subprocess.run([sys.executable, str(DISPATCH), *args],
                          input=stdin, capture_output=True, text=True, timeout=120)


def test_prompt_la_CHU_khong_phai_duong_dan():
    """Ca gãy nguyên bản: chuỗi có dấu, có khoảng trắng — chắc chắn không phải file."""
    r = _chay(["dsh", "--prompt", "xin chào đây là văn bản", "--dump-config"])
    assert "No such file or directory" not in r.stderr + r.stdout
    assert r.returncode == 0


def test_khong_con_rut_gon_tien_to_ngam():
    """`--time` từng được argparse đoán thành `--timeout`. Đoán mò là gốc của BUG-12."""
    r = _chay(["dsh", "--time", "30", "--prompt", "x", "--result-json"])
    assert r.returncode == 2
    d = json.loads(r.stdout)
    assert d["status"] == "blocked"
    assert "unrecognized arguments" in d["summary"]


def test_prompt_va_prompt_file_loai_tru_nhau(tmp_path):
    f = tmp_path / "p.txt"; f.write_text("nội dung", encoding="utf-8")
    r = _chay(["dsh", "--prompt", "chữ", "--prompt-file", str(f), "--result-json"])
    assert r.returncode == 2
    assert "loại trừ nhau" in json.loads(r.stdout)["summary"]


def test_prompt_rong_bi_chan():
    r = _chay(["dsh", "--prompt", "   ", "--result-json"])
    assert r.returncode == 2
    assert "rỗng" in json.loads(r.stdout)["summary"]
