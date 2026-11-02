"""Việc 5 — smoke test "máy sạch": KHÔNG vendor nào, KHÔNG API key, HOME/XDG rỗng.
P1: vendor thiếu ⇒ degrade (skipped/blocked) có JSON hợp lệ, không traceback, không crash.
Đồng thời chốt Python tối thiểu = 3.11+ thống nhất với SPEC."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
VENDORS = ["agy", "codex", "gemini", "grok", "dsh", "claude", "opencode", "hermes", "openrouter"]


@pytest.fixture
def env_sach(tmp_path):
    empty = tmp_path / "emptybin"; empty.mkdir()
    env = {"PATH": str(empty), "HOME": str(tmp_path / "home"), "LANG": "C.UTF-8",
           "PYTHONIOENCODING": "utf-8"}
    for k in ("XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        env[k] = str(tmp_path / k.lower())
    (tmp_path / "home").mkdir()
    return env


def _py(args, env, cwd):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True,
                          timeout=60, env=env, cwd=cwd)


def test_doctor_may_sach(env_sach, tmp_path):
    r = _py([str(BIN / "doctor.py")], env_sach, tmp_path)
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr
    for v in ("codex", "agy", "dsh", "claude"):
        assert re.search(rf"^{v}\s*\|\s*not_installed", r.stdout, re.M), v


@pytest.mark.parametrize("vendor", VENDORS)
def test_dispatch_may_sach_degrade(env_sach, tmp_path, vendor):
    r = _py([str(BIN / "dispatch.py"), vendor, "--prompt", "hi", "--result-json"], env_sach, tmp_path)
    assert "Traceback" not in r.stderr, r.stderr
    res = json.loads(r.stdout)
    assert {"status", "summary", "warnings"} <= res.keys()
    assert res["status"] in ("skipped", "blocked"), res
    assert r.returncode != 0


def test_python_toi_thieu_thong_nhat_311():
    assert "Python 3.11+" in (ROOT / "SPEC.md").read_text(encoding="utf-8")
    assert "Python 3.11+" in (ROOT / "README.md").read_text(encoding="utf-8")
    for f in ("README.md", "requirements.txt"):
        assert "3.9+" not in (ROOT / f).read_text(encoding="utf-8"), f
    for f in ("dispatch.py", "doctor.py", "failover.py", "watcher.py", "populate.py"):
        assert "sys.version_info < (3, 11)" in (BIN / f).read_text(encoding="utf-8"), f
