"""BUG-18 — grok bị trần chung 120s giết oan (đo 19/09: 157s cho prompt 2KB, 55/141 lượt timeout).

Không truyền --timeout thì phải dùng default_timeout riêng của vendor trong vendors.json.
"""
from lib.vendor_config import default_timeout, load_vendor_config


def test_grok_co_timeout_rieng_du_dai():
    assert default_timeout("grok") >= 300


def test_vendor_khong_khai_bao_thi_ve_120():
    cfg = {"vendors": {"x": {}}}
    assert default_timeout("x", cfg) == 120


def test_gia_tri_ngoai_1_600_bi_bo_qua():
    cfg = {"vendors": {"x": {"default_timeout": 9999}, "y": {"default_timeout": "300"}}}
    assert default_timeout("x", cfg) == 120
    assert default_timeout("y", cfg) == 120


def test_vendors_json_moi_default_timeout_hop_le():
    for name, v in load_vendor_config()["vendors"].items():
        if "default_timeout" in v:
            assert type(v["default_timeout"]) is int and 1 <= v["default_timeout"] <= 600, name


# ── Codex review 19/09: test ở tầng CLI, không chỉ helper ────────────────────
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

DISPATCH = Path(__file__).resolve().parents[1] / "bin" / "dispatch.py"


def _nap_dispatch():
    spec = importlib.util.spec_from_file_location("dispatch_bug18", DISPATCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _chay_main(mod, monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["dispatch.py", *argv])
    try:
        mod.main()
    except SystemExit:
        pass


def test_cli_khong_truyen_timeout_thi_grok_nhan_300(monkeypatch, capsys):
    mod = _nap_dispatch()
    seen = {}

    def fake_run_vendor(**kw):
        seen.update(kw)
        from lib.dispatch_core import DispatchResult
        return DispatchResult(status="ok", vendor=kw["vendor"], model=kw["model"],
                              summary="x", warnings=[], stdout="OK", exit_code=0)

    monkeypatch.setattr(mod, "run_vendor", fake_run_vendor)
    _chay_main(mod, monkeypatch, ["grok", "--prompt", "x", "--no-traps", "--result-json"])
    assert seen["timeout"] == default_timeout("grok") >= 300


def test_cli_timeout_tuong_minh_khong_bi_de(monkeypatch):
    mod = _nap_dispatch()
    seen = {}

    def fake_run_vendor(**kw):
        seen.update(kw)
        from lib.dispatch_core import DispatchResult
        return DispatchResult(status="ok", vendor=kw["vendor"], model=kw["model"],
                              summary="x", warnings=[], stdout="OK", exit_code=0)

    monkeypatch.setattr(mod, "run_vendor", fake_run_vendor)
    _chay_main(mod, monkeypatch, ["grok", "--timeout", "45", "--prompt", "x", "--no-traps", "--result-json"])
    assert seen["timeout"] == 45


def test_cli_timeout_0_bi_chan_khong_bi_thay_bang_mac_dinh():
    r = subprocess.run([sys.executable, str(DISPATCH), "grok", "--timeout", "0", "--prompt", "x",
                        "--no-traps", "--result-json"], capture_output=True, text=True, timeout=60)
    d = json.loads(r.stdout)
    assert d["status"] == "blocked"
    assert "1-600" in d["summary"]


def test_exception_van_ghi_evidence_kem_latency(monkeypatch):
    mod = _nap_dispatch()
    ghi = []
    import lib.evidence as ev
    monkeypatch.setattr(ev, "append_evidence", lambda rec: ghi.append(rec))

    def no(**kw):
        raise OSError("binary biến mất giữa chừng")

    monkeypatch.setattr(mod, "run_vendor", no)
    monkeypatch.setattr(sys, "argv", ["dispatch.py", "grok", "--prompt", "x", "--no-traps"])
    with pytest.raises(OSError):
        mod.main()
    assert ghi and ghi[-1]["status"] == "error"
    assert isinstance(ghi[-1]["latency_ms"], int)
    assert "OSError" in ghi[-1]["reason"]


def test_bool_va_config_hong_ve_fallback():
    assert default_timeout("x", {"vendors": {"x": {"default_timeout": True}}}) == 120
    assert default_timeout("x", {"vendors": None}) == 120
    assert default_timeout("x", {"vendors": {"x": "hỏng"}}) == 120
