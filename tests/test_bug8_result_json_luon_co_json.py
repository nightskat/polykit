"""BUG-8 (20/08/2026): `--result-json` hứa stdout là JSON, nhưng ở các nhánh chặn
SỚM (model không hợp lệ, --prompt-file không đọc được, --prompt-file rỗng) nó
`sys.exit(2)` sau khi in lỗi ra stderr, còn stdout rỗng 0 byte → caller
`json.loads(stdout)` nổ JSONDecodeError và bỏ sót thông báo lỗi rất tốt kia.

Sửa: khi có --result-json, nhánh chặn in DispatchResult(status=blocked) ra stdout
(vẫn exit 2, khác 1 của lỗi vendor), warnings giữ nguyên nội dung lỗi gốc.
Không có cờ → y như cũ: stdout rỗng, lỗi ở stderr."""
import json
import subprocess
import sys
from pathlib import Path

DISPATCH = Path(__file__).resolve().parents[1] / "bin" / "dispatch.py"


def _run(args, stdin=""):
    return subprocess.run([sys.executable, str(DISPATCH), *args],
                          input=stdin, capture_output=True, text=True, timeout=60)


def _goi_model_sai():
    return _run(["dsh", "model-khong-ton-tai", "--result-json"])


def test_model_sai_stdout_parse_duoc_va_co_du_field():
    r = _goi_model_sai()
    assert r.returncode == 2
    ket_qua = json.loads(r.stdout)
    # Dùng đúng hợp đồng DispatchResult (status, vendor, model, summary, warnings,
    # stdout, exit_code, reason, served_model).
    assert set(ket_qua.keys()) == {
        "status", "vendor", "model", "summary", "warnings", "stdout",
        "exit_code", "reason", "served_model",
    }
    assert ket_qua["status"] == "blocked"
    assert ket_qua["vendor"] == "dsh"
    assert ket_qua["model"] == "model-khong-ton-tai"
    assert ket_qua["exit_code"] == 2
    assert ket_qua["reason"] == "guard_violation"
    assert ket_qua["served_model"] is None


def test_model_sai_giu_nguyen_noi_dung_loi_trong_warnings():
    r = _goi_model_sai()
    ket_qua = json.loads(r.stdout)
    noi_dung = "\n".join(ket_qua["warnings"])
    # 3 ý của thông báo gốc phải còn đủ: model sai, danh sách hợp lệ, gợi ý bypass.
    assert "model 'model-khong-ton-tai' not in vendor 'dsh' valid models" in noi_dung
    assert "Valid models:" in noi_dung
    assert "deepseek-v4-pro" in noi_dung
    assert "Use --allow-unknown-model to bypass." in noi_dung


def test_prompt_file_khong_ton_tai_van_co_json(tmp_path):
    f = tmp_path / "khong-co.txt"
    r = _run(["dsh", "--prompt-file", str(f), "--result-json"])
    assert r.returncode == 2
    ket_qua = json.loads(r.stdout)
    assert ket_qua["status"] == "blocked"
    assert ket_qua["exit_code"] == 2
    assert ket_qua["reason"] == "guard_violation"
    assert "không đọc được --prompt-file" in ket_qua["summary"]
    assert any("không đọc được --prompt-file" in w for w in ket_qua["warnings"])


def test_prompt_file_rong_van_co_json(tmp_path):
    f = tmp_path / "rong.txt"
    f.write_text("   \n", encoding="utf-8")
    r = _run(["dsh", "--prompt-file", str(f), "--result-json"])
    assert r.returncode == 2
    ket_qua = json.loads(r.stdout)
    assert ket_qua["status"] == "blocked"
    assert ket_qua["exit_code"] == 2
    assert ket_qua["reason"] == "guard_violation"
    assert "--prompt-file rỗng" in ket_qua["summary"]
    assert any("--prompt-file rỗng" in w for w in ket_qua["warnings"])


def test_khong_co_result_json_thi_stdout_van_rong_loi_van_o_stderr(tmp_path):
    """Đối chứng: KHÔNG có --result-json thì hành vi y như cũ — stdout rỗng,
    lỗi vẫn ra stderr, exit 2."""
    r = _run(["dsh", "model-khong-ton-tai"])
    assert r.returncode == 2
    assert r.stdout == ""
    assert "model 'model-khong-ton-tai' not in vendor" in r.stderr

    f = tmp_path / "rong.txt"
    f.write_text("   \n", encoding="utf-8")
    r = _run(["dsh", "--prompt-file", str(f)])
    assert r.returncode == 2
    assert r.stdout == ""
    assert "rỗng" in r.stderr


# ── hai chỗ rò Codex review chỉ ra (20/08) ─────────────────────────────────

def _chay(args):
    import subprocess, sys as _s
    from pathlib import Path as _P
    d = _P(__file__).resolve().parents[1] / "bin" / "dispatch.py"
    return subprocess.run([_s.executable, str(d), *args],
                          input="", capture_output=True, text=True, timeout=120)


def test_loi_CO_dong_lenh_van_ra_json():
    """argparse xử lý TRƯỚC code mình: vendor sai / option lạ đều exit 2 với
    stdout rỗng, kể cả khi người gọi đã xin --result-json."""
    import json
    for args in (["khong-co-vendor", "--result-json"], ["codex", "--co-la-gi-do", "--result-json"]):
        r = _chay(args)
        assert r.returncode == 2, args
        d = json.loads(r.stdout)
        assert d["status"] == "blocked" and d["reason"] == "guard_violation"
        assert any("usage:" in w for w in d["warnings"]), "phải giữ usage để sửa được lệnh"


def test_loi_CO_dong_lenh_KHONG_co_co_thi_van_nhu_cu():
    r = _chay(["khong-co-vendor"])
    assert r.returncode == 2 and r.stdout == "" and "invalid choice" in r.stderr


def test_doctor_cung_ton_trong_result_json():
    import json
    r = _chay(["openrouter", "--doctor", "--result-json"])
    d = json.loads(r.stdout)
    assert d["status"] in ("ok", "error")
    if d["status"] == "error":
        assert d["reason"] == "doctor_failed"
