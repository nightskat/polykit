"""served_model = model THẬT đã chạy, khác `model` đã yêu cầu.

Sinh ra sau bench router OpenRouter 2026-08-03: gọi `openrouter/auto` thì
gemini-2.5-flash-lite chạy ($0,000026), gọi `openrouter/fusion` thì claude-opus-5
chạy (~$1/lượt khi prompt mở). Không có field này = không biết tiền đi đâu.
"""
from __future__ import annotations

import json

from lib.dispatch_core import DispatchResult
from lib.dispatcher import run_vendor
from lib.evidence import make_record
from lib.openrouter import or_dispatch


def _fake_opener(payload: dict):
    class FakeResponse:
        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    def opener(req, timeout):
        return FakeResponse()

    return opener


def test_or_dispatch_bắt_được_model_router_đã_chọn():
    opener = _fake_opener({
        "model": "google/gemini-2.5-flash-lite",
        "provider": "Google",
        "choices": [{"message": {"content": "hi"}}],
    })
    res = or_dispatch("hello", model="openrouter/auto", key="fake", opener=opener)
    assert res.ok
    assert res.served_model == "google/gemini-2.5-flash-lite"
    assert res.provider == "Google"


def test_or_dispatch_response_thiếu_field_thì_none_chứ_không_vỡ():
    # Response cũ/không chuẩn: vẫn phải ok, served_model=None (không bịa).
    res = or_dispatch("hello", key="fake",
                      opener=_fake_opener({"choices": [{"message": {"content": "hi"}}]}))
    assert res.ok and res.text == "hi"
    assert res.served_model is None and res.provider is None


def test_dispatch_openrouter_gắn_served_model_và_nêu_trong_summary():
    import lib.dispatcher as d

    def fake_or_dispatch(prompt, model="auto", timeout=120):
        from lib.openrouter import ORResult
        return ORResult(ok=True, text="ok", served_model="anthropic/claude-opus-5")

    orig = d.or_dispatch if hasattr(d, "or_dispatch") else None
    import lib.openrouter as oro
    saved = oro.or_dispatch
    oro.or_dispatch = fake_or_dispatch
    try:
        res = run_vendor(vendor="openrouter", prompt="x", model="openrouter/fusion")
    finally:
        oro.or_dispatch = saved
        if orig is not None:
            d.or_dispatch = orig

    assert res.status == "ok"
    assert res.served_model == "anthropic/claude-opus-5"
    assert "served: anthropic/claude-opus-5" in res.summary


def test_model_auto_thì_served_model_none_chứ_không_ghi_auto(make_probe):
    # codex `auto`: CLI tự chọn default, ta KHÔNG biết → None, không được bịa "auto".
    class Res:
        returncode = 0
        stdout = "done"
        stderr = ""

    res = run_vendor(vendor="codex", prompt="x", model="auto",
                     runner=lambda cmd, **kw: Res(),
                     detector=lambda spec: make_probe("codex", "/usr/bin/codex"))
    assert res.status == "ok"
    assert res.served_model is None


def test_model_ghim_thì_served_model_bằng_chính_nó(make_probe):
    class Res:
        returncode = 0
        stdout = "done"
        stderr = ""

    res = run_vendor(vendor="codex", prompt="x", model="gpt-5.5",
                     runner=lambda cmd, **kw: Res(),
                     detector=lambda spec: make_probe("codex", "/usr/bin/codex"))
    assert res.served_model == "gpt-5.5"


def test_dispatch_result_to_dict_có_khoá_served_model():
    d = DispatchResult(status="ok", vendor="openrouter", model="openrouter/auto",
                       summary="s", served_model="google/gemini-2.5-flash-lite").to_dict()
    assert d["served_model"] == "google/gemini-2.5-flash-lite"
    assert d["model"] == "openrouter/auto"  # cái đã YÊU CẦU vẫn giữ nguyên


def test_evidence_record_ghi_cả_hai_model():
    rec = make_record("openrouter", "openrouter/fusion", "ok", "2026-08-03T00:00:00Z",
                      served_model="anthropic/claude-opus-5")
    assert rec["model"] == "openrouter/fusion"
    assert rec["served_model"] == "anthropic/claude-opus-5"


def test_evidence_record_cũ_không_truyền_served_model_vẫn_chạy():
    rec = make_record("codex", "auto", "ok", "2026-08-03T00:00:00Z")
    assert rec["served_model"] is None
