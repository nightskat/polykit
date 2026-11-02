"""BUG-19 — `--result-json`: stdout là ĐÚNG MỘT JSON, mọi log sang stderr.
Regression 3 đường: thành công / lỗi vendor / --doctor. Vendor GIẢ, không gọi thật."""
import json
import subprocess
import sys
from pathlib import Path

from fake_cli import make_fake_agy

DISPATCH = Path(__file__).resolve().parents[1] / "bin" / "dispatch.py"


def _mot_json(stdout: str) -> dict:
    obj, end = json.JSONDecoder().raw_decode(stdout.lstrip())
    assert stdout.lstrip()[end:].strip() == "", f"stdout còn rác sau JSON: {stdout!r}"
    assert isinstance(obj, dict)
    return obj


def _run(args, env):
    # KHÔNG --no-traps: trap/progress phải sang stderr, không làm bẩn stdout.
    return subprocess.run([sys.executable, str(DISPATCH), "agy", *args, "--result-json"],
                          capture_output=True, text=True, timeout=60, env=env)


def test_thanh_cong(tmp_path):
    r = _run(["--prompt", "hello"], make_fake_agy(tmp_path))
    res = _mot_json(r.stdout)
    assert res["status"] == "ok" and r.returncode == 0
    assert "traps for agy" in r.stderr  # log vẫn có, nhưng ở stderr


def test_loi_vendor(tmp_path):
    r = _run(["--prompt", "FAIL"], make_fake_agy(tmp_path))
    res = _mot_json(r.stdout)
    assert r.returncode == 1
    assert res["status"] != "ok"


def test_doctor_stdout_cua_verify_cmd_sang_stderr(tmp_path):
    r = _run(["--doctor"], make_fake_agy(tmp_path))
    res = _mot_json(r.stdout)
    assert res["status"] == "ok", r.stderr
    assert "fake doctor stdout" not in r.stdout
    assert "fake doctor stdout" in r.stderr


def test_chan_som_van_mot_json(tmp_path):
    r = _run(["--prompt", ""], make_fake_agy(tmp_path))
    assert _mot_json(r.stdout)["status"] == "blocked"


def test_khong_result_json_doctor_van_in_stdout_nhu_cu(tmp_path):
    env = make_fake_agy(tmp_path)
    r = subprocess.run([sys.executable, str(DISPATCH), "agy", "--doctor"],
                       capture_output=True, text=True, timeout=60, env=env)
    assert "fake doctor stdout" in r.stdout
