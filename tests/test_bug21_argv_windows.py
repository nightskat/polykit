"""BUG-21 (P5) — lệnh vendor không chạy được trên Windows.

1. Lane argv (`["claude", ...]`) chạy subprocess không shell ⇒ CreateProcess
   không áp PATHEXT ⇒ `claude.cmd` (npm) không bao giờ được tìm thấy.
2. `--doctor` chạy verify_cmd bằng shell=True với nháy POSIX (`agy -p '/model'`)
   ⇒ cmd.exe truyền nguyên dấu `'` cho vendor.
Test không cần Windows: chốt argv[0] được resolve tuyệt đối theo PATH của env, và
verify_cmd được tách thành argv không còn dấu nháy."""
import json
import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from lib import dispatcher  # noqa: E402
from lib.dispatcher import resolve_argv0, run_vendor  # noqa: E402


def _exe(d: Path, name: str) -> Path:
    p = d / name
    p.write_text("#!/bin/sh\necho hi\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


def test_resolve_argv0_theo_path_cua_env(tmp_path, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("dùng file thực thi POSIX; nhánh Windows phủ bởi test_vong6 + CI")
    exe = _exe(tmp_path, "claude")
    monkeypatch.setenv("PATH", "")  # PATH tiến trình cha KHÔNG có vendor
    out = resolve_argv0(["claude", "-p", "x"], env={"PATH": str(tmp_path)})
    assert out == [str(exe), "-p", "x"]


def test_resolve_argv0_giu_nguyen_duong_dan_va_lenh_la(tmp_path):
    assert resolve_argv0(["/abs/claude", "a"]) == ["/abs/claude", "a"]
    assert resolve_argv0(["khong-ton-tai-xyz", "a"], env={"PATH": str(tmp_path)}) == ["khong-ton-tai-xyz", "a"]
    assert resolve_argv0("chuoi shell") == "chuoi shell"


def test_run_vendor_mac_dinh_dung_runner_resolve(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        raise FileNotFoundError("stop")

    monkeypatch.setattr(dispatcher, "resolve_argv0", lambda c, e=None: ["/resolved/" + c[0], *c[1:]])
    monkeypatch.setattr(dispatcher.subprocess, "run", fake_run)
    # runner mặc định là subprocess.run gốc ⇒ phải được bọc bởi resolving_run
    assert dispatcher.resolving_run is not None
    try:
        dispatcher.resolving_run(["claude", "-p", "x"])
    except FileNotFoundError:
        pass
    assert seen["cmd"][0] == "/resolved/claude"


def test_doctor_argv_bo_dau_nhay_posix():
    import importlib.util
    spec = importlib.util.spec_from_file_location("dispatch_cli", ROOT / "bin" / "dispatch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    argv = mod._doctor_argv("khong-ton-tai-xyz -p '/model'")
    assert argv == ["khong-ton-tai-xyz", "-p", "/model"]


def test_vendors_json_verify_cmd_khong_dung_tinh_nang_shell():
    cfg = json.loads((ROOT / "config" / "vendors.json").read_text(encoding="utf-8"))
    for name, v in cfg["vendors"].items():
        for line in [v.get("verify_cmd")] + list(v.get("zero_quota_cmds") or []):
            if line:
                assert not any(ch in line for ch in "|&;<>$`"), (name, line)
