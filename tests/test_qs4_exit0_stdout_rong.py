"""QUAN SÁT-4 — vendor thoát 0 nhưng stdout rỗng KHÔNG được báo ok.

20/08 agy chỉ in banner rồi thoát, dispatch coi là xong ⇒ caller không có gì để
nghiệm thu. Giờ: status=error, reason=empty_output, exit≠0, giữ stderr làm bằng
chứng. Riêng --expect-artifact: stdout im là hợp lệ, artifact quyết định.
Chỉ dùng agy GIẢ (tests/fake_cli.py)."""
import json
import subprocess
import sys
from pathlib import Path

from fake_cli import make_fake_agy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from lib.dispatcher import _classify_completed  # noqa: E402

DISPATCH = Path(__file__).resolve().parents[1] / "bin" / "dispatch.py"


class _Res:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _run(args, env):
    return subprocess.run([sys.executable, str(DISPATCH), "agy", *args, "--result-json", "--no-traps"],
                          capture_output=True, text=True, timeout=60, env=env)


def test_classify_exit0_stdout_rong_la_error():
    r = _classify_completed("agy", "m", _Res(0, "  \n", "banner trap\n"))
    assert r.status == "error"
    assert r.reason == "empty_output"
    assert r.served_model is None
    assert any("banner trap" in w for w in r.warnings)


def test_classify_stdout_chi_la_prompt_echo_cung_la_rong():
    r = _classify_completed("codex", "m", _Res(0, "câu hỏi gốc\n", ""), prompt="câu hỏi gốc")
    assert r.reason == "empty_output"


def test_classify_co_stdout_van_ok():
    r = _classify_completed("agy", "m", _Res(0, "OK\n", ""))
    assert r.status == "ok" and r.reason is None


def test_cli_agy_silent_tra_error_va_mot_json(tmp_path):
    env = make_fake_agy(tmp_path)
    r = _run(["--prompt", "SILENT"], env)
    res = json.loads(r.stdout)
    assert r.returncode == 1
    assert res["status"] == "error"
    assert res["reason"] == "empty_output"
    assert any("banner" in w for w in res["warnings"])


def test_cli_expect_artifact_im_lang_nhung_co_file_van_ok(tmp_path):
    env = make_fake_agy(tmp_path)
    out = tmp_path / "out.txt"
    r = _run(["--sandbox", "workspace-write", "--expect-artifact", str(out),
              "--prompt", f"WRITE:{out} SILENT"], env)
    res = json.loads(r.stdout)
    assert r.returncode == 0, r.stderr
    assert res["status"] == "ok" and out.exists()


def test_cli_expect_artifact_im_lang_khong_file_la_artifact_missing(tmp_path):
    env = make_fake_agy(tmp_path)
    r = _run(["--sandbox", "workspace-write", "--expect-artifact", str(tmp_path / "x.txt"),
              "--prompt", "SILENT"], env)
    res = json.loads(r.stdout)
    assert r.returncode == 1
    assert res["reason"] == "artifact_missing"
