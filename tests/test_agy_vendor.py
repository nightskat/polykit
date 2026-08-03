"""Vendor `agy` đứng riêng — không còn là lane con của gemini.

Fixture bám đúng ma trận Grok red-team đòi (2026-08-03): unauth, catalog rỗng,
stdout rác, chưa cài, và slug không-Gemini phải dispatch được.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

from lib.dispatch_core import AGY_DEFAULT_MODEL, build_agy_cmd
from lib.dispatcher import run_vendor
from lib.states import VendorState, classify
from lib.vendors import REGISTRY, detect, parse_models

AGY_OUT = """gemini-3.6-flash-high
gemini-3.6-flash-medium
gemini-3.1-pro-low
claude-sonnet-4-6
claude-opus-4-6-thinking
gpt-oss-120b-medium
"""


class _Res:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_agy_co_trong_registry_va_la_vendor_rieng():
    spec = REGISTRY["agy"]
    assert spec.binary == "agy"
    assert spec.models_cmd == ["agy", "models"]
    # KHÔNG được là bí danh của gemini
    assert REGISTRY["gemini"].binary == "gemini"


def test_detect_agy_ready_va_dien_catalog():
    def runner(cmd, **kw):
        return _Res(0, "1.1.9") if "--version" in cmd else _Res(0, AGY_OUT)

    p = detect(REGISTRY["agy"], which=lambda b: "/usr/local/bin/agy", runner=runner)
    assert classify(p) == VendorState.READY
    assert p.version == "1.1.9"
    assert "claude-sonnet-4-6" in p.models and "gpt-oss-120b-medium" in p.models
    assert len(p.models) == 6
    assert p.error is None


def test_catalog_rong_van_ready_nhung_co_tin_hieu_su_co():
    # Grok P0: không được im lặng khoe khoẻ, cũng không được bịa list tĩnh.
    def runner(cmd, **kw):
        return _Res(0, "1.1.9") if "--version" in cmd else _Res(0, "   \n")

    p = detect(REGISTRY["agy"], which=lambda b: "/usr/local/bin/agy", runner=runner)
    assert classify(p) == VendorState.READY
    assert p.models == []
    assert p.error == "catalog_empty"


def test_chua_auth_thi_khong_ready():
    def runner(cmd, **kw):
        return _Res(0, "1.1.9") if "--version" in cmd else _Res(1, "", "not logged in")

    p = detect(REGISTRY["agy"], which=lambda b: "/usr/local/bin/agy", runner=runner)
    assert classify(p) == VendorState.INSTALLED_NOT_AUTHED
    assert p.models == []


def test_chua_cai_thi_not_installed():
    p = detect(REGISTRY["agy"], which=lambda b: None, runner=lambda *a, **k: _Res())
    assert classify(p) == VendorState.NOT_INSTALLED


def test_parse_models_loai_banner_va_ansi():
    raw = (
        "\x1b[1mAvailable models:\x1b[0m\n"
        "  * gemini-3.6-flash-medium\n"
        "Default model: gemini-3.6-flash-medium\n"
        "claude-sonnet-4-6\n"
        "WARNING: catalog may be stale\n"
        "gemini-3.6-flash-medium\n"  # trùng
    )
    assert parse_models(raw) == ["gemini-3.6-flash-medium", "claude-sonnet-4-6"]


def test_auto_giu_dung_default_cua_agy_sh():
    # Grok P1: đổi default ngầm = phá kỳ vọng lệnh đang chạy.
    assert AGY_DEFAULT_MODEL == "gemini-3.6-flash-medium"
    assert build_agy_cmd("auto", "x")[:3] == ["agy", "--model", AGY_DEFAULT_MODEL]
    assert build_agy_cmd("claude-sonnet-4-6", "x")[2] == "claude-sonnet-4-6"


def test_dispatch_agy_chay_duoc_slug_khong_phai_gemini(monkeypatch):
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"] = cmd
        return _Res(0, "pong")

    res = run_vendor(vendor="agy", prompt="ping", model="claude-sonnet-4-6",
                     runner=runner,
                     detector=lambda spec: detect(
                         spec, which=lambda b: "/usr/local/bin/agy",
                         runner=lambda c, **k: _Res(0, AGY_OUT)))
    assert res.status == "ok" and res.stdout == "pong"
    assert res.served_model == "claude-sonnet-4-6"
    assert "--model" in seen["cmd"] and "claude-sonnet-4-6" in seen["cmd"]


def test_dispatch_agy_thieu_binary_thi_skipped_khong_crash():
    res = run_vendor(vendor="agy", prompt="ping",
                     runner=lambda *a, **k: _Res(),
                     detector=lambda spec: detect(spec, which=lambda b: None,
                                                  runner=lambda *a, **k: _Res()))
    assert res.status == "skipped"
    assert res.reason == "not_installed"


def test_gemini_van_chay_nhu_cu(make_probe):
    # Tương thích ngược: lane 1 của gemini vẫn là agy, không hard-fail (Grok P1).
    from lib.dispatcher import _dispatch_gemini
    res = _dispatch_gemini("ping", "auto", 30,
                           lambda cmd, **kw: _Res(0, "pong"), {})
    assert res.status == "ok"
    assert res.served_model.startswith("agy:")


def test_parse_models_nhan_slug_dung_dau_dong_kem_mo_ta():
    # Codex review P1: `agy models` in dạng bảng thì bắt cả dòng sẽ mất sạch catalog.
    raw = (
        "gemini-3.6-flash-medium   Google Gemini Flash (default)\n"
        "* claude-sonnet-4-6  Anthropic\n"
        "models\n"          # từ đơn — không phải slug
        "default\n"
        "Available models:\n"
    )
    assert parse_models(raw) == ["gemini-3.6-flash-medium", "claude-sonnet-4-6"]


def test_auth_check_rot_vi_quota_thi_ra_quota_capped_khong_phai_not_authed():
    # Codex review P1: hết quota ≠ chưa đăng nhập. Bảo user đi login lại là sai lane.
    def runner(cmd, **kw):
        if "--version" in cmd:
            return _Res(0, "1.1.10")
        return _Res(1, "", "Error: quota exceeded for this project")

    p = detect(REGISTRY["agy"], which=lambda b: "/usr/local/bin/agy", runner=runner)
    assert p.authed is True
    assert classify(p) == VendorState.QUOTA_CAPPED


def test_catalog_in_ra_stderr_van_doc_duoc():
    def runner(cmd, **kw):
        if "--version" in cmd:
            return _Res(0, "1.1.10")
        return _Res(0, "", AGY_OUT)

    p = detect(REGISTRY["agy"], which=lambda b: "/usr/local/bin/agy", runner=runner)
    assert "claude-sonnet-4-6" in p.models
    assert p.error is None


def test_auto_chon_tu_catalog_live_khi_default_bien_mat():
    # Codex review P1: catalog đổi mùa mà `auto` vẫn ghim slug cũ thì dispatch gãy.
    future = "gemini-4.0-flash-medium\nclaude-sonnet-9\n"
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"] = cmd
        return _Res(0, "pong")

    res = run_vendor(vendor="agy", prompt="ping", model="auto", runner=runner,
                     detector=lambda spec: detect(
                         spec, which=lambda b: "/usr/local/bin/agy",
                         runner=lambda c, **k: _Res(0, "1.1.10") if "--version" in c
                         else _Res(0, future)))
    assert res.served_model == "gemini-4.0-flash-medium"
    assert "gemini-3.6-flash-medium" not in seen["cmd"]


def test_snapshot_tu_choi_ghi_de_file_khong_phai_may_sinh(tmp_path):
    # Codex review P1: gõ nhầm --snapshot bin/dispatch.py là mất source.
    import subprocess as sp
    victim = tmp_path / "source.py"
    victim.write_text("print('đừng ghi đè tôi')\n", encoding="utf-8")
    repo = pathlib.Path(__file__).resolve().parents[1]
    r = sp.run([sys.executable, str(repo / "bin/watcher.py"), "--dry-run",
                "--snapshot", str(victim)], capture_output=True, text=True, timeout=300)
    assert "print('đừng ghi đè tôi')" in victim.read_text(encoding="utf-8")
    assert "snapshot_error" in r.stdout
