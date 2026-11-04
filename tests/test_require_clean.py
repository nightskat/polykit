import pytest
"""Việc 4 — `--require-clean` (opt-in): checker PII inject được, chặn TRƯỚC mọi probe/spawn."""
import json
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import lib.clean_gate as cg
from fake_cli import make_fake_agy, read_calls
from lib.dispatcher import run_vendor

@pytest.fixture(autouse=True)
def _train_lane(monkeypatch):
    """Cơ chế PII gate giờ chỉ chạy cho lane train (TRAINS_ON_DATA); Go adapter
    chỉ duyệt profile paid nên ép lane train để giữ kiểm cơ chế checker."""
    import lib.go_data_gate as gdg
    monkeypatch.setattr(gdg, "_trains_on_data", lambda model: True)


DISPATCH = Path(__file__).resolve().parents[1] / "bin" / "dispatch.py"


class _Spy:
    def __init__(self):
        self.probed, self.spawned = [], []

    def detector(self, spec):
        self.probed.append(spec.name)
        raise AssertionError("không được probe")

    def runner(self, cmd, **kw):
        self.spawned.append(cmd)
        raise AssertionError("không được spawn")


def _checker(rc):
    calls = []

    def _r(cmd, **kw):
        calls.append(cmd)
        # checker nhận file prompt, không nhận prompt qua argv
        assert cmd[1] == "check" and Path(cmd[2]).exists()
        m = MagicMock(); m.returncode = rc; m.stdout = "SĐT 0912xxxxxx"; m.stderr = ""
        return m
    return _r, calls


def test_pii_chan_truoc_probe_spawn(monkeypatch):
    monkeypatch.delenv(cg.CHECKER_ENV, raising=False)
    monkeypatch.setattr(cg, "_which", lambda n: "/fake/pg-redact")
    r, calls = _checker(1)
    monkeypatch.setattr(cg, "_checker_runner", r)
    spy = _Spy()
    res = run_vendor("codex", "KH Nguyen Van A 0912345678", require_clean=True,
                     runner=spy.runner, detector=spy.detector)
    assert res.status == "blocked" and res.reason == "pii_detected"
    assert calls and spy.probed == [] and spy.spawned == []
    blob = json.dumps(res.to_dict(), ensure_ascii=False)
    assert "0912345678" not in blob and "0912xxxxxx" not in blob  # không lộ prompt/output checker


def test_thieu_checker_fail_closed(monkeypatch):
    monkeypatch.delenv(cg.CHECKER_ENV, raising=False)
    monkeypatch.setattr(cg, "_which", lambda n: None)
    spy = _Spy()
    res = run_vendor("codex", "hi", require_clean=True, runner=spy.runner, detector=spy.detector)
    assert res.reason == "clean_checker_missing" and spy.spawned == [] and spy.probed == []


def test_checker_loi_fail_closed(monkeypatch):
    monkeypatch.delenv(cg.CHECKER_ENV, raising=False)
    monkeypatch.setattr(cg, "_which", lambda n: "/fake/pg-redact")

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("pg-redact", 20)
    monkeypatch.setattr(cg, "_checker_runner", boom)
    spy = _Spy()
    res = run_vendor("codex", "hi", require_clean=True, runner=spy.runner, detector=spy.detector)
    assert res.reason == "clean_check_failed" and spy.spawned == []


def test_sach_thi_chay_va_co_warning(monkeypatch):
    monkeypatch.delenv(cg.CHECKER_ENV, raising=False)
    monkeypatch.setattr(cg, "_which", lambda n: "/fake/pg-redact")
    r, _ = _checker(0)
    monkeypatch.setattr(cg, "_checker_runner", r)
    from lib.states import VendorProbe
    det = lambda s: VendorProbe(name=s.name, path="/fake", authed=True, quota_capped=False,
                                version="1", models=[], error=None)
    ok = MagicMock(); ok.returncode = 0; ok.stdout = "OK"; ok.stderr = ""
    res = run_vendor("codex", "def f(): pass", require_clean=True,
                     runner=lambda *a, **k: ok, detector=det)
    assert res.status == "ok"
    assert any("--require-clean" in w for w in res.warnings)


def test_khong_opt_in_thi_khong_goi_checker(monkeypatch):
    called = []
    monkeypatch.setattr(cg, "_which", lambda n: called.append(n) or None)
    from lib.states import VendorProbe
    det = lambda s: VendorProbe(name=s.name, path="/fake", authed=True, quota_capped=False,
                                version="1", models=[], error=None)
    ok = MagicMock(); ok.returncode = 0; ok.stdout = "OK"; ok.stderr = ""
    assert run_vendor("codex", "hi", runner=lambda *a, **k: ok, detector=det).status == "ok"
    assert called == []


def _fake_checker(tmp_path, rc):
    # Python + shim .cmd trên Windows (shebang không chạy được ở đó).
    from fake_cli import install_python_shim
    d = tmp_path / f"checkerbin{rc}"; d.mkdir()
    return str(install_python_shim(d, "checker", f"#!{sys.executable}\nimport sys; sys.exit({rc})\n"))


def test_cli_checker_gia_chan_agy_khong_bi_goi(tmp_path):
    env = make_fake_agy(tmp_path)
    env[cg.CHECKER_ENV] = _fake_checker(tmp_path, 3)
    r = subprocess.run([sys.executable, str(DISPATCH), "agy", "--require-clean",
                        "--prompt", "hello", "--result-json"],
                       capture_output=True, text=True, timeout=60, env=env)
    res = json.loads(r.stdout)
    assert res["status"] == "blocked" and res["reason"] == "pii_detected"
    assert read_calls(env) == []  # agy giả KHÔNG được gọi, kể cả --version/models (probe)


def test_cli_checker_gia_sach_thi_chay(tmp_path):
    env = make_fake_agy(tmp_path)
    env[cg.CHECKER_ENV] = _fake_checker(tmp_path, 0)
    r = subprocess.run([sys.executable, str(DISPATCH), "agy", "--require-clean",
                        "--prompt", "hello", "--result-json"],
                       capture_output=True, text=True, timeout=60, env=env)
    assert json.loads(r.stdout)["status"] == "ok"
