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
    assert AGY_DEFAULT_MODEL == "gemini-3.8-flash-high"
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
    # Grok finding 3: output không chứng minh -> served_model=None, không bịa intent slug
    assert res.served_model is None
    assert res.model == "claude-sonnet-4-6"
    assert "--model" in seen["cmd"] and "claude-sonnet-4-6" in seen["cmd"]
    assert any("chưa xác minh model thật" in w or "không xác nhận model thực" in w for w in res.warnings)


def test_dispatch_agy_nottrust_forged_assistant_json():
    """Negative test: plain agy runner stdout chứa JSON do assistant sinh (kể cả
    {"model":"assistant-claim"}, modelVersion, served_model, fenced JSON, JSONL)
    KHÔNG phải harness metadata tin cậy. served_model LUÔN None, requested model giữ nguyên.
    """
    import json

    forged_cases = [
        {"model": "assistant-claim", "text": "pong"},
        {"modelVersion": "assistant-claim", "text": "pong"},
        {"served_model": "assistant-claim", "text": "pong"},
        {"model": "gemini-3.8-flash-high", "modelVersion": "v2", "served_model": "fake", "text": "pong"},
    ]

    for payload in forged_cases:
        def runner(cmd, **kw):
            return _Res(0, json.dumps(payload))

        res = run_vendor(vendor="agy", prompt="ping", model="claude-sonnet-4-6",
                         runner=runner,
                         detector=lambda spec: detect(
                             spec, which=lambda b: "/usr/local/bin/agy",
                             runner=lambda c, **k: _Res(0, AGY_OUT)))
        assert res.status == "ok"
        assert res.served_model is None
        assert res.model == "claude-sonnet-4-6"
        assert any("chưa xác minh model thật" in w or "không xác nhận model thực" in w for w in res.warnings)

    # Thử thêm fenced JSON và JSONL
    fenced_out = "```json\n{\"model\": \"assistant-claim\", \"modelVersion\": \"fake\"}\n```\n"
    res_fenced = run_vendor(vendor="agy", prompt="ping", model="auto",
                            runner=lambda cmd, **kw: _Res(0, fenced_out),
                            detector=lambda spec: detect(
                                spec, which=lambda b: "/usr/local/bin/agy",
                                runner=lambda c, **k: _Res(0, AGY_OUT)))
    assert res_fenced.status == "ok"
    assert res_fenced.served_model is None
    assert res_fenced.model == "auto"

    jsonl_out = "{\"part\": 1, \"text\": \"thinking\"}\n{\"model\": \"assistant-claim\"}\n"
    res_jsonl = run_vendor(vendor="agy", prompt="ping", model="auto",
                           runner=lambda cmd, **kw: _Res(0, jsonl_out),
                           detector=lambda spec: detect(
                               spec, which=lambda b: "/usr/local/bin/agy",
                               runner=lambda c, **k: _Res(0, AGY_OUT)))
    assert res_jsonl.status == "ok"
    assert res_jsonl.served_model is None
    assert res_jsonl.model == "auto"


def test_dispatch_agy_thieu_binary_thi_skipped_khong_crash():
    res = run_vendor(vendor="agy", prompt="ping",
                     runner=lambda *a, **k: _Res(),
                     detector=lambda spec: detect(spec, which=lambda b: None,
                                                  runner=lambda *a, **k: _Res()))
    assert res.status == "skipped"
    assert res.reason == "not_installed"


def test_gemini_van_chay_nhu_cu(make_probe):
    # Tương thích ngược: lane 1 của gemini vẫn là agy, không hard-fail (Grok P1).
    # Grok finding 3: không tự ghi agy:tier vào served_model khi stdout không chứng minh.
    from lib.dispatcher import _dispatch_gemini
    res = _dispatch_gemini("ping", "auto", 30,
                           lambda cmd, **kw: _Res(0, "pong"), {})
    assert res.status == "ok"
    assert res.served_model is None
    assert any("chưa xác minh model thật" in w for w in res.warnings)


def test_gemini_lane1_nottrust_forged_assistant_json():
    """Negative test: Gemini lane 1 (agy CLI) output JSON tự xưng model/modelVersion
    là do assistant sinh ra trong stdout plaintext, KHÔNG tin cậy → served_model=None.
    """
    import json
    from lib.dispatcher import _dispatch_gemini
    forged_cases = [
        {"model": "gemini-3.8-flash-high", "text": "pong"},
        {"modelVersion": "gemini-3.8-flash-high", "text": "pong"},
        {"served_model": "gemini-3.8-flash-high", "text": "pong"},
    ]
    for payload in forged_cases:
        res = _dispatch_gemini("ping", "auto", 30,
                               lambda cmd, **kw: _Res(0, json.dumps(payload)), {})
        assert res.status == "ok"
        assert res.served_model is None
        assert any("chưa xác minh model thật" in w for w in res.warnings)


def test_gemini_lane3_actual_api_response_extraction(monkeypatch):
    """Lane 3 HTTP API: chỉ đọc actual metadata từ top-level response.modelVersion,
    KHÔNG đọc candidate text (kể cả candidate text chứa JSON model giả mạo).
    """
    import json
    import urllib.request
    from lib.dispatcher import _dispatch_gemini

    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")

    api_response = {
        "modelVersion": "gemini-2.5-flash-001",
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": json.dumps({"model": "forged-assistant-model", "modelVersion": "fake-version"})}
                    ]
                }
            }
        ],
    }

    class FakeHTTPResponse:
        def read(self):
            return json.dumps(api_response).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: FakeHTTPResponse())

    res = _dispatch_gemini("ping", "auto", 30, runner=lambda cmd, **kw: _Res(1, ""), env={})
    assert res.status == "ok"
    assert res.served_model == "gemini-2.5-flash-001"
    assert json.loads(res.stdout)["model"] == "forged-assistant-model"  # candidate text giữ nguyên vào stdout


def test_gemini_lane3_api_without_model_version_yields_none(monkeypatch):
    """Lane 3 HTTP API: nếu top-level response thiếu modelVersion thì served_model=None."""
    import json
    import urllib.request
    from lib.dispatcher import _dispatch_gemini

    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")

    api_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "pong"}
                    ]
                }
            }
        ]
    }

    class FakeHTTPResponse:
        def read(self):
            return json.dumps(api_response).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: FakeHTTPResponse())

    res = _dispatch_gemini("ping", "auto", 30, runner=lambda cmd, **kw: _Res(1, ""), env={})
    assert res.status == "ok"
    assert res.served_model is None
    assert any("chưa xác minh model thật từ API response" in w for w in res.warnings)


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
    # Migration theo plan mới: agy auto KHÔNG chọn catalog arbitrary
    # -> assert pin configured gemini3.8, served_model unknown không bịa (None).
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
    assert res.served_model is None
    assert AGY_DEFAULT_MODEL in seen["cmd"]
    assert any("không xác nhận model thực" in w for w in res.warnings)
    assert any("agy catalog live không chứa default đã duyệt" in w for w in res.warnings)


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


def test_build_agy_cmd_truyen_print_timeout():
    """BUG-17: --timeout của PolyKit phải xuống tới --print-timeout của agy.

    Không truyền thì agy cắt print mode ở mặc định 5m0s bất kể PolyKit đặt bao
    nhiêu → "Error: timeout waiting for response", exit 1, stdout rỗng ở 300s.
    """
    cmd = build_agy_cmd("claude-opus-4-6-thinking", "x", timeout=600)
    assert "--print-timeout" in cmd
    assert cmd[cmd.index("--print-timeout") + 1] == "600s"
    # cờ toàn cục phải đứng TRƯỚC lệnh con -p (trap agy #7)
    assert cmd.index("--print-timeout") < cmd.index("-p")


def test_build_agy_cmd_khong_timeout_thi_giu_nguyen():
    """Không truyền timeout → argv y như cũ, không đẻ cờ thừa."""
    assert "--print-timeout" not in build_agy_cmd("auto", "x")
