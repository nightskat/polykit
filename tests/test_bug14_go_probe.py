"""Tests cho BUG-14: doctor và dispatch dùng chung probe evidence.

Mục tiêu:
- Tận dụng successful live dispatch evidence gần đây đúng vendor/provider/model/quota group.
- Có TTL rõ (AUTH_PROBE_TTL, mặc định 1h).
- Explicit auth failure mới không bị override (authed=False / installed_not_authed).
- KHÔNG assume_authed=True vô căn cứ, KHÔNG đọc secrets/credential.
- Catalog listing không phải auth proof.
- Regression fixture recent success => doctor ready + detect used dispatch same.
- stale/future/malformed/wrong provider/vendor/real auth failure stays unverified/notauthed.
- quota cap newest wins.
- Giữ sibling behavior vendor khác.
- State vẫn schema_version=1, warnings provenance/timestamp.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from lib.states import VendorProbe, VendorState, classify
from lib.vendors import REGISTRY, VendorSpec, detect, detect_all
from lib.doctor_quota import (
    AUTH_FUTURE_SKEW,
    AUTH_PROBE_TTL,
    evaluate_auth_evidence,
    is_explicit_auth_failure_record,
    matches_vendor_criteria,
)
from doctor import run_doctor, render_table

NOW = "2026-10-22T12:00:00+00:00"
NOW_DT = datetime.fromisoformat(NOW)


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def fake_runner_ok(cmd, **kw):
    if "--version" in cmd:
        return FakeCompleted(returncode=0, stdout="v1.0.0")
    if "models" in cmd:
        return FakeCompleted(returncode=0, stdout="opencode-go/deepseek-v4.1-flash\n")
    return FakeCompleted(returncode=0)


def fake_which(path: str = "/fake/bin/app"):
    return lambda b: path


# ==============================================================================
# 1. Pure helper tests: evaluate_auth_evidence & matches_vendor_criteria
# ==============================================================================

def test_matches_vendor_criteria_strict():
    # Đúng vendor
    rec = {"vendor": "opencode", "model": "opencode-go/deepseek-v4.1-flash"}
    assert matches_vendor_criteria(rec, "opencode", provider="opencode-go") is True

    # Sai vendor
    assert matches_vendor_criteria(rec, "hermes", provider="opencode-go") is False
    assert matches_vendor_criteria(rec, "codex") is False

    # Sai provider
    rec_wrong_p = {"vendor": "opencode", "provider": "wrong-provider"}
    assert matches_vendor_criteria(rec_wrong_p, "opencode", provider="opencode-go") is False

    # Sai quota group
    rec_wrong_qg = {"vendor": "opencode", "quota_group": "other-group"}
    assert matches_vendor_criteria(rec_wrong_qg, "opencode", quota_group="opencode-go") is False

    # Sai model prefix
    rec_wrong_model = {"vendor": "opencode", "model": "openai/gpt-4"}
    assert matches_vendor_criteria(rec_wrong_model, "opencode", provider="opencode-go") is False


def test_is_explicit_auth_failure_record():
    assert is_explicit_auth_failure_record({"status": "auth_failure"}) is True
    assert is_explicit_auth_failure_record({"reason": "unauthenticated"}) is True
    assert is_explicit_auth_failure_record({"reason": "login_required"}) is True
    assert is_explicit_auth_failure_record({"stderr": "Error: not logged in"}) is True
    assert is_explicit_auth_failure_record({"error": "unauthorized access"}) is True
    # Không phải auth failure
    assert is_explicit_auth_failure_record({"status": "ok"}) is False
    assert is_explicit_auth_failure_record({"status": "error", "reason": "timeout"}) is False


def test_evaluate_auth_evidence_recent_success():
    recent_ts = (NOW_DT - timedelta(minutes=10)).isoformat()
    # Shape legacy thật của dispatch (lib.evidence.make_record): có model, KHÔNG có
    # provider/quota_group.
    records = [{"vendor": "opencode", "model": "deepseek-v4.1-flash", "status": "ok", "ts": recent_ts}]
    res = evaluate_auth_evidence(records, "opencode", NOW, provider="opencode-go")
    assert res["authed"] is True
    assert res["evidence_ts"] == recent_ts
    assert res["reason"] == "recent_dispatch_success"


def test_evaluate_auth_evidence_stale_exceeds_ttl():
    stale_ts = (NOW_DT - timedelta(hours=2)).isoformat()  # > AUTH_PROBE_TTL 1h
    records = [{"vendor": "opencode", "model": "deepseek-v4.1-flash", "status": "ok", "ts": stale_ts}]
    res = evaluate_auth_evidence(records, "opencode", NOW, provider="opencode-go")
    assert res["authed"] is None
    assert "stale_evidence" in str(res["reason"])


def test_evaluate_auth_evidence_future_ts_ignored():
    future_ts = (NOW_DT + timedelta(minutes=10)).isoformat()
    records = [{"vendor": "opencode", "status": "ok", "ts": future_ts}]
    res = evaluate_auth_evidence(records, "opencode", NOW, provider="opencode-go")
    assert res["authed"] is None
    assert res["reason"] == "no_evidence"


def test_evaluate_auth_evidence_malformed_records():
    records = [
        "not a dict",
        None,
        {"vendor": "opencode"},  # missing ts
        {"vendor": "opencode", "ts": "invalid-ts", "status": "ok"},
        {"ts": NOW, "status": "ok"},  # missing vendor
    ]
    res = evaluate_auth_evidence(records, "opencode", NOW)
    assert res["authed"] is None


def test_evaluate_auth_evidence_explicit_auth_failure_newest_wins():
    old_ok_ts = (NOW_DT - timedelta(minutes=30)).isoformat()
    new_fail_ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    records = [
        {"vendor": "opencode", "status": "ok", "ts": old_ok_ts},
        {"vendor": "opencode", "status": "error", "reason": "unauthenticated", "ts": new_fail_ts},
    ]
    res = evaluate_auth_evidence(records, "opencode", NOW, provider="opencode-go")
    # Explicit auth failure mới hơn -> authed=False, không bị override
    assert res["authed"] is False
    assert res["evidence_ts"] == new_fail_ts
    assert res["reason"] == "unauthenticated"


def test_evaluate_auth_evidence_newer_success_clears_older_auth_failure():
    old_fail_ts = (NOW_DT - timedelta(minutes=30)).isoformat()
    new_ok_ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    records = [
        {"vendor": "opencode", "model": "deepseek-v4.1-flash", "status": "error",
         "reason": "unauthenticated", "ts": old_fail_ts},
        {"vendor": "opencode", "model": "deepseek-v4.1-flash", "status": "ok", "ts": new_ok_ts},
    ]
    res = evaluate_auth_evidence(records, "opencode", NOW, provider="opencode-go")
    assert res["authed"] is True
    assert res["evidence_ts"] == new_ok_ts


# ==============================================================================
# 2. Regression: recent success => doctor ready + detect used dispatch same
# ==============================================================================

def test_opencode_recent_success_makes_doctor_ready_and_detect_ready(monkeypatch):
    monkeypatch.setattr("doctor.write_state", lambda s, path=None: path)
    recent_ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    records = [
        {
            "vendor": "opencode",
            "model": "opencode-go/deepseek-v4.1-flash",
            "provider": "opencode-go",
            "quota_group": "opencode-go",
            "status": "ok",
            "ts": recent_ts,
        }
    ]

    # 1. detect() độc lập (cách dispatch gọi)
    p = detect(
        REGISTRY["opencode"],
        which=fake_which("/fake/home/.opencode/bin/opencode"),
        runner=fake_runner_ok,
        records=records,
        now=NOW,
    )
    assert p.path == "/fake/home/.opencode/bin/opencode"
    assert p.authed is True
    assert p.quota_capped is False
    assert classify(p) == VendorState.READY

    # 2. doctor.run_doctor() dùng cùng cơ sở evidence
    monkeypatch.setattr("doctor.read_evidence", lambda limit=500, path=None: records)
    state = run_doctor(probes=[p], now=NOW, records=records)

    assert state["schema_version"] == 1
    vdata = state["vendors"]["opencode"]
    assert vdata["state"] == "ready"
    assert vdata["auth_evidence_ts"] == recent_ts
    assert vdata["auth_evidence_source"] == "dispatch_log"

    # Warnings provenance và timestamp
    expected_msg = f"[opencode] auth xác minh từ live dispatch lúc {recent_ts}"
    assert any(expected_msg in w for w in vdata.get("warnings", []))
    assert any(expected_msg in w for w in state.get("warnings", []))

    # Render table ghi nhận sẵn sàng từ live dispatch
    tbl = render_table(state)
    assert f"auth xác minh từ live dispatch lúc {recent_ts}" in tbl


def test_hermes_recent_success_makes_doctor_ready_and_detect_ready(monkeypatch):
    monkeypatch.setattr("doctor.write_state", lambda s, path=None: path)
    recent_ts = (NOW_DT - timedelta(minutes=15)).isoformat()
    records = [
        {
            "vendor": "hermes",
            "model": "deepseek-v4.1-flash",
            "provider": "opencode-go",
            "status": "ok",
            "ts": recent_ts,
        }
    ]

    # 1. detect()
    p = detect(
        REGISTRY["hermes"],
        which=fake_which("/usr/local/bin/hermes"),
        runner=fake_runner_ok,
        records=records,
        now=NOW,
    )
    assert p.authed is True
    assert classify(p) == VendorState.READY

    # 2. run_doctor()
    state = run_doctor(probes=[p], now=NOW, records=records)
    vdata = state["vendors"]["hermes"]
    assert vdata["state"] == "ready"
    assert vdata["auth_evidence_ts"] == recent_ts


# ==============================================================================
# 3. Negative tests: stale, future, malformed, wrong vendor/provider
# ==============================================================================

def test_stale_success_stays_auth_unverified(monkeypatch):
    monkeypatch.setattr("doctor.write_state", lambda s, path=None: path)
    stale_ts = (NOW_DT - timedelta(hours=3)).isoformat()
    records = [{"vendor": "opencode", "model": "deepseek-v4.1-flash", "status": "ok", "ts": stale_ts}]

    p = detect(
        REGISTRY["opencode"],
        which=fake_which("/fake/home/.opencode/bin/opencode"),
        runner=fake_runner_ok,
        records=records,
        now=NOW,
    )
    assert p.authed is None
    assert classify(p) == VendorState.AUTH_UNVERIFIED

    state = run_doctor(probes=[p], now=NOW, records=records)
    assert state["vendors"]["opencode"]["state"] == "auth_unverified"


def test_future_success_stays_auth_unverified(monkeypatch):
    monkeypatch.setattr("doctor.write_state", lambda s, path=None: path)
    future_ts = (NOW_DT + timedelta(minutes=5)).isoformat()
    records = [{"vendor": "opencode", "status": "ok", "ts": future_ts}]

    p = detect(
        REGISTRY["opencode"],
        which=fake_which("/fake/home/.opencode/bin/opencode"),
        runner=fake_runner_ok,
        records=records,
        now=NOW,
    )
    assert p.authed is None
    assert classify(p) == VendorState.AUTH_UNVERIFIED

    state = run_doctor(probes=[p], now=NOW, records=records)
    assert state["vendors"]["opencode"]["state"] == "auth_unverified"


def test_wrong_vendor_success_stays_auth_unverified(monkeypatch):
    monkeypatch.setattr("doctor.write_state", lambda s, path=None: path)
    recent_ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    # Thành công trên codex hoặc dsh không được nhận vơ cho opencode
    records = [{"vendor": "codex", "status": "ok", "ts": recent_ts}]

    p = detect(
        REGISTRY["opencode"],
        which=fake_which("/fake/home/.opencode/bin/opencode"),
        runner=fake_runner_ok,
        records=records,
        now=NOW,
    )
    assert p.authed is None
    assert classify(p) == VendorState.AUTH_UNVERIFIED

    state = run_doctor(probes=[p], now=NOW, records=records)
    assert state["vendors"]["opencode"]["state"] == "auth_unverified"


def test_wrong_provider_stays_auth_unverified(monkeypatch):
    recent_ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    records = [{"vendor": "opencode", "provider": "openai-direct", "status": "ok", "ts": recent_ts}]

    p = detect(
        REGISTRY["opencode"],
        which=fake_which("/fake/home/.opencode/bin/opencode"),
        runner=fake_runner_ok,
        records=records,
        now=NOW,
    )
    assert p.authed is None
    assert classify(p) == VendorState.AUTH_UNVERIFIED


def test_real_auth_failure_stays_installed_not_authed(monkeypatch):
    monkeypatch.setattr("doctor.write_state", lambda s, path=None: path)
    fail_ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    records = [{"vendor": "opencode", "status": "error", "reason": "unauthorized", "ts": fail_ts}]

    p = detect(
        REGISTRY["opencode"],
        which=fake_which("/fake/home/.opencode/bin/opencode"),
        runner=fake_runner_ok,
        records=records,
        now=NOW,
    )
    assert p.authed is False
    assert classify(p) == VendorState.INSTALLED_NOT_AUTHED

    state = run_doctor(probes=[p], now=NOW, records=records)
    assert state["vendors"]["opencode"]["state"] == "installed_not_authed"


# ==============================================================================
# 4. Quota cap newest wins
# ==============================================================================

def test_quota_cap_newest_wins_over_recent_success(monkeypatch):
    monkeypatch.setattr("doctor.write_state", lambda s, path=None: path)
    ok_ts = (NOW_DT - timedelta(minutes=20)).isoformat()
    cap_ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    records = [
        {"vendor": "opencode", "model": "deepseek-v4.1-flash", "status": "ok", "ts": ok_ts},
        {"vendor": "opencode", "status": "quota_capped", "ts": cap_ts},
    ]

    # detect() thấy quota_capped=True
    p = detect(
        REGISTRY["opencode"],
        which=fake_which("/fake/home/.opencode/bin/opencode"),
        runner=fake_runner_ok,
        records=records,
        now=NOW,
    )
    assert p.authed is True
    assert p.quota_capped is True
    assert classify(p) == VendorState.QUOTA_CAPPED

    # doctor.run_doctor() ra quota_capped
    state = run_doctor(probes=[p], now=NOW, records=records)
    assert state["vendors"]["opencode"]["state"] == "quota_capped"


# ==============================================================================
# 5. Catalog listing không phải auth proof & không assume_authed vô căn cứ
# ==============================================================================

def test_catalog_listing_is_not_auth_proof():
    # Catalog có 10 models nhưng không có dispatch evidence -> vẫn auth_unverified
    def runner_with_many_models(cmd, **kw):
        if "--version" in cmd:
            return FakeCompleted(returncode=0, stdout="opencode 1.0.0")
        if "models" in cmd:
            catalog = "\n".join([f"opencode-go/model-{i}" for i in range(10)])
            return FakeCompleted(returncode=0, stdout=catalog)
        return FakeCompleted(returncode=0)

    p = detect(
        REGISTRY["opencode"],
        which=fake_which("/fake/home/.opencode/bin/opencode"),
        runner=runner_with_many_models,
        records=[],
        now=NOW,
    )
    assert len(p.models) == 10
    assert p.authed is None
    assert classify(p) == VendorState.AUTH_UNVERIFIED
    # Cấm assume_authed=True trong spec
    assert REGISTRY["opencode"].assume_authed is None
    assert REGISTRY["hermes"].assume_authed is None


def test_missing_binary_stays_not_installed_even_with_evidence():
    # Binary chưa cài thì dù có record ok cũng không báo ready
    recent_ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    records = [{"vendor": "opencode", "status": "ok", "ts": recent_ts}]
    p = detect(
        REGISTRY["opencode"],
        which=lambda b: None,
        records=records,
        now=NOW,
    )
    assert p.path is None
    assert classify(p) == VendorState.NOT_INSTALLED


# ==============================================================================
# 6. Preserves sibling behavior of other vendors
# ==============================================================================

def test_sibling_vendors_behavior_preserved():
    # 1. Claude: assume_authed=True -> ready
    p_claude = detect(REGISTRY["claude"], which=fake_which("/bin/claude"), runner=fake_runner_ok)
    assert classify(p_claude) == VendorState.READY

    # 2. Codex: auth_check_cmd rớt authoritative -> installed_not_authed
    def runner_codex_fail(cmd, **kw):
        if "--version" in cmd:
            return FakeCompleted(returncode=0, stdout="codex 1.0")
        if "login" in cmd:
            return FakeCompleted(returncode=1, stderr="not logged in")
        return FakeCompleted(returncode=0)

    p_codex = detect(REGISTRY["codex"], which=fake_which("/bin/codex"), runner=runner_codex_fail)
    assert classify(p_codex) == VendorState.INSTALLED_NOT_AUTHED

    # 3. DSH: dump-config exit 0 -> ready
    def runner_dsh_ok(cmd, **kw):
        if "--version" in cmd:
            return FakeCompleted(returncode=0, stdout="dsh 0.1.0")
        if "--dump-config" in cmd:
            return FakeCompleted(returncode=0, stdout="config: ok")
        return FakeCompleted(returncode=0)

    p_dsh = detect(REGISTRY["dsh"], which=fake_which("/bin/dsh"), runner=runner_dsh_ok)
    assert classify(p_dsh) == VendorState.READY


# ==============================================================================
# 7. Regression BUG-14 lô 5a: evidence CHỈ áp cho lane Go + phải có timestamp
#    (dispatcher gọi detect(spec) không truyền `now` → từng nổ AttributeError
#    `NoneType.isoformat()` và CLI mất cả result JSON.)
# ==============================================================================

def test_non_go_detect_without_records_or_now_ignores_go_evidence(monkeypatch):
    """Vendor ngoài lane Go không được đọc/áp evidence — và không bao giờ nổ khi
    caller (dispatcher) không truyền `now`."""
    recent_ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    go_ok = [
        {"vendor": "opencode", "provider": "opencode-go", "status": "ok", "ts": recent_ts},
        {"vendor": "hermes", "provider": "opencode-go", "status": "ok", "ts": recent_ts},
    ]
    monkeypatch.setattr("lib.evidence.read_evidence", lambda limit=200, path=None: go_ok)

    # claude: assume_authed=True -> ready, không đụng evidence lane Go
    p_claude = detect(REGISTRY["claude"], which=fake_which("/bin/claude"), runner=fake_runner_ok)
    assert p_claude.authed is True
    assert classify(p_claude) == VendorState.READY

    # gemini: probe phụ không authoritative + stderr không phải auth failure
    # -> auth_unverified, KHÔNG được nâng ready nhờ evidence Go
    def runner_gemini_unverified(cmd, **kw):
        if "--version" in cmd:
            return FakeCompleted(returncode=0, stdout="gemini 1.0")
        return FakeCompleted(returncode=1, stderr="network unreachable")

    p_gemini = detect(REGISTRY["gemini"], which=fake_which("/bin/gemini"),
                      runner=runner_gemini_unverified)
    assert p_gemini.authed is None
    assert classify(p_gemini) == VendorState.AUTH_UNVERIFIED

    # codex: auth check authoritative rớt -> installed_not_authed
    def runner_codex_fail(cmd, **kw):
        if "--version" in cmd:
            return FakeCompleted(returncode=0, stdout="codex 1.0")
        return FakeCompleted(returncode=1, stderr="not logged in")

    p_codex = detect(REGISTRY["codex"], which=fake_which("/bin/codex"), runner=runner_codex_fail)
    assert classify(p_codex) == VendorState.INSTALLED_NOT_AUTHED


def test_go_detect_without_now_uses_system_clock_and_does_not_crash(monkeypatch):
    """detect(opencode) không có `now` (đường dispatcher) vẫn chạy: mốc thời gian
    được chuẩn hoá, không gọi .isoformat() trên None."""
    recent_ts = datetime.now(timezone.utc).isoformat()
    records = [{"vendor": "opencode", "provider": "opencode-go", "status": "ok", "ts": recent_ts}]
    monkeypatch.setattr("lib.evidence.read_evidence", lambda limit=200, path=None: records)

    p = detect(REGISTRY["opencode"], which=fake_which("/fake/home/.opencode/bin/opencode"),
               runner=fake_runner_ok)
    assert p.authed is True
    assert classify(p) == VendorState.READY


def test_go_evidence_record_without_ts_is_not_proof():
    """Bản ghi thiếu/ts hỏng không phải bằng chứng auth, dù đúng vendor."""
    records = [
        {"vendor": "opencode", "status": "ok"},
        {"vendor": "opencode", "status": "ok", "ts": "not-a-timestamp"},
        {"vendor": "opencode", "status": "ok", "ts": None},
    ]
    p = detect(REGISTRY["opencode"], which=fake_which("/fake/home/.opencode/bin/opencode"),
               runner=fake_runner_ok, records=records, now=NOW)
    assert p.authed is None
    assert classify(p) == VendorState.AUTH_UNVERIFIED


def test_doctor_auth_evidence_scoped_to_go_lane(monkeypatch):
    """doctor không lấy bằng chứng của vendor khác để đổi trạng thái vendor ngoài
    lane Go (gemini giữ auth_unverified dù có record ok của chính nó)."""
    monkeypatch.setattr("doctor.write_state", lambda s, path=None: path)
    recent_ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    records = [{"vendor": "gemini", "status": "ok", "ts": recent_ts}]
    probe = VendorProbe(
        name="gemini",
        path="/bin/gemini",
        authed=None,
        quota_capped=False,
        version="1.0",
        models=[],
    )
    state = run_doctor(probes=[probe], now=NOW, records=records)
    vdata = state["vendors"]["gemini"]
    assert vdata["state"] == "auth_unverified"
    assert "auth_evidence_ts" not in vdata


# ==============================================================================
# 8. Grok finding 1: marker auth phải khớp CỤM TỪ, không so chuỗi bằng nhau.
#    Regression: reason "login required" / "unauthorized: …" từng bị bỏ qua dù mới
#    hơn bản ghi ok → doctor báo ready trong khi vendor đã mất auth.
# ==============================================================================

@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "not_logged_in"),
        ("status", "login_required"),
        ("status", "auth_failure"),
        ("reason", "login required"),
        ("reason", "unauthorized: token expired"),
        ("reason", "Not Logged In"),
        ("reason", "authentication required"),
        ("reason", "unauthenticated"),
        ("error", "401 unauthorized"),
        ("error", "Auth failure: token revoked"),
        ("stderr", "Error: login-required (run login)"),
        ("summary", "dispatch failed: unauthorized"),
        ("summary", "not logged in"),
    ],
)
def test_is_explicit_auth_failure_record_phrase_variants(field, value):
    assert is_explicit_auth_failure_record({"status": "error", field: value}) is True


@pytest.mark.parametrize(
    "value",
    [
        "ok",
        "authorized",
        "not unauthorized",
        "not_unauthorized",
        "no unauthorized access",
        "preauthorized",
        "unauthorizedness",
        "network unreachable",
    ],
)
def test_is_explicit_auth_failure_record_requires_bounded_words(value):
    # Biên từ + luật phủ định: KHÔNG match substring tuỳ tiện, KHÔNG biến câu
    # phủ định ("not unauthorized") thành bằng chứng lỗi auth.
    assert is_explicit_auth_failure_record({"status": "ok", "summary": value}) is False
    assert is_explicit_auth_failure_record({"status": "error", "reason": value}) is False


def test_newer_auth_failure_reason_overrides_ok():
    """Finding 1 ở tầng evaluate: reason mới hơn phải thắng bản ghi ok."""
    ok_ts = (NOW_DT - timedelta(minutes=10)).isoformat()
    fail_ts = (NOW_DT - timedelta(minutes=2)).isoformat()
    records = [
        {"vendor": "opencode", "model": "deepseek-v4.1-flash", "status": "ok", "ts": ok_ts},
        {"vendor": "opencode", "model": "deepseek-v4.1-flash", "status": "error",
         "reason": "login required", "ts": fail_ts},
    ]
    res = evaluate_auth_evidence(records, "opencode", NOW, provider="opencode-go")
    assert res["authed"] is False
    assert res["evidence_ts"] == fail_ts
    assert res["reason"] == "login required"


def test_newer_auth_failure_from_stderr_overrides_ok(monkeypatch):
    """Cùng regression nhưng ở detect(): vendor phải ra installed_not_authed."""
    monkeypatch.setattr("doctor.write_state", lambda s, path=None: path)
    ok_ts = (NOW_DT - timedelta(minutes=10)).isoformat()
    fail_ts = (NOW_DT - timedelta(minutes=1)).isoformat()
    records = [
        {"vendor": "opencode", "model": "deepseek-v4.1-flash", "status": "ok", "ts": ok_ts},
        {"vendor": "opencode", "model": "deepseek-v4.1-flash", "status": "error",
         "stderr": "Unauthorized: token expired", "ts": fail_ts},
    ]
    p = detect(
        REGISTRY["opencode"],
        which=fake_which("/fake/home/.opencode/bin/opencode"),
        runner=fake_runner_ok,
        records=records,
        now=NOW,
    )
    assert p.authed is False
    assert classify(p) == VendorState.INSTALLED_NOT_AUTHED


# ==============================================================================
# 9. Finding 2: chính sách mốc thời gian TƯƠNG LAI (AUTH_FUTURE_SKEW = 5s)
#    - success tương lai: KHÔNG BAO GIỜ promote (kể cả trong skew)
#    - failure tường minh trong skew: tính → fail-closed, thắng ok hợp lệ
#    - quá skew: bỏ hẳn (không poison vĩnh viễn)
# ==============================================================================

def _future(seconds: float) -> str:
    return (NOW_DT + timedelta(seconds=seconds)).isoformat()


def test_auth_future_skew_constant_is_5s():
    assert AUTH_FUTURE_SKEW == timedelta(seconds=5)


@pytest.mark.parametrize("offset", [1, 3, 5, 3600])
def test_future_success_never_promotes(offset):
    records = [{"vendor": "opencode", "model": "deepseek-v4.1-flash",
                "status": "ok", "ts": _future(offset)}]
    res = evaluate_auth_evidence(records, "opencode", NOW, provider="opencode-go")
    assert res["authed"] is None
    assert res["reason"] == "no_evidence"


def test_future_failure_within_skew_fails_closed_over_valid_ok():
    ok_ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    records = [
        {"vendor": "opencode", "model": "deepseek-v4.1-flash", "status": "ok", "ts": ok_ts},
        {"vendor": "opencode", "model": "deepseek-v4.1-flash", "status": "error",
         "reason": "login required", "ts": _future(3)},
    ]
    res = evaluate_auth_evidence(records, "opencode", NOW, provider="opencode-go")
    assert res["authed"] is False


def test_future_failure_beyond_skew_ignored_so_ok_still_wins():
    ok_ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    records = [
        {"vendor": "opencode", "model": "deepseek-v4.1-flash", "status": "ok", "ts": ok_ts},
        {"vendor": "opencode", "model": "deepseek-v4.1-flash", "status": "error",
         "reason": "login required", "ts": _future(6)},
    ]
    res = evaluate_auth_evidence(records, "opencode", NOW, provider="opencode-go")
    assert res["authed"] is True
    assert res["evidence_ts"] == ok_ts


def test_future_failure_boundary_exact_skew_inclusive():
    # Đúng 5s: còn trong skew → tính (fail-closed).
    ok_ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    base = {"vendor": "opencode", "model": "deepseek-v4.1-flash", "status": "ok", "ts": ok_ts}
    at_skew = dict(base)
    at_skew.update({"status": "error", "reason": "unauthenticated", "ts": _future(5)})
    res = evaluate_auth_evidence([base, at_skew], "opencode", NOW, provider="opencode-go")
    assert res["authed"] is False

    # 5s + 1µs: vượt skew → bỏ, ok hợp lệ thắng.
    beyond = dict(base)
    beyond.update({"status": "error", "reason": "unauthenticated",
                   "ts": (NOW_DT + AUTH_FUTURE_SKEW + timedelta(microseconds=1)).isoformat()})
    res2 = evaluate_auth_evidence([base, beyond], "opencode", NOW, provider="opencode-go")
    assert res2["authed"] is True


def test_far_future_failure_does_not_poison_detect(monkeypatch):
    monkeypatch.setattr("doctor.write_state", lambda s, path=None: path)
    fail_ts = (NOW_DT + timedelta(hours=2)).isoformat()
    records = [{"vendor": "opencode", "model": "deepseek-v4.1-flash",
                "status": "error", "reason": "login required", "ts": fail_ts}]
    p = detect(
        REGISTRY["opencode"],
        which=fake_which("/fake/home/.opencode/bin/opencode"),
        runner=fake_runner_ok,
        records=records,
        now=NOW,
    )
    # ts rác tương lai xa không được ghim vendor vào installed_not_authed
    assert p.authed is None
    assert classify(p) == VendorState.AUTH_UNVERIFIED


# ==============================================================================
# 10. Metadata hỏng: type-validate rồi TỪ CHỐI, không crash (.strip trên int/list)
# ==============================================================================

@pytest.mark.parametrize(
    "record",
    [
        {"vendor": "opencode", "provider": 42, "model": "deepseek-v4.1-flash"},
        {"vendor": "opencode", "provider": ["opencode-go"], "model": "deepseek-v4.1-flash"},
        {"vendor": "opencode", "provider": "", "model": "deepseek-v4.1-flash"},
        {"vendor": "opencode", "quota_group": [], "model": "deepseek-v4.1-flash"},
        {"vendor": "opencode", "quota_group": {}, "model": "deepseek-v4.1-flash"},
        {"vendor": "opencode", "quota_group": 42, "model": "deepseek-v4.1-flash"},
        {"vendor": "opencode", "model": 42},
        {"vendor": 42, "model": "deepseek-v4.1-flash"},
        {"vendor": "", "model": "deepseek-v4.1-flash"},
        {"model": "deepseek-v4.1-flash"},
    ],
)
def test_matches_vendor_criteria_rejects_malformed_metadata(record):
    # Chỉ cần KHÔNG ném AttributeError/TypeError; và kết quả phải là False.
    assert matches_vendor_criteria(record, "opencode", provider="opencode-go",
                                   quota_group="opencode-go") is False


def test_malformed_provider_42_record_is_not_evidence():
    ts = (NOW_DT - timedelta(minutes=2)).isoformat()
    records = [{"vendor": "opencode", "provider": 42, "quota_group": [],
                "model": "deepseek-v4.1-flash", "status": "ok", "ts": ts}]
    res = evaluate_auth_evidence(records, "opencode", NOW,
                                 provider="opencode-go", quota_group="opencode-go")
    assert res["authed"] is None
    assert res["reason"] == "no_evidence"


def test_malformed_metadata_does_not_promote_in_detect(monkeypatch):
    monkeypatch.setattr("doctor.write_state", lambda s, path=None: path)
    ts = (NOW_DT - timedelta(minutes=2)).isoformat()
    records = [{"vendor": "opencode", "provider": 42, "quota_group": [],
                "model": "deepseek-v4.1-flash", "status": "ok", "ts": ts}]
    p = detect(
        REGISTRY["opencode"],
        which=fake_which("/fake/home/.opencode/bin/opencode"),
        runner=fake_runner_ok,
        records=records,
        now=NOW,
    )
    assert p.authed is None
    assert classify(p) == VendorState.AUTH_UNVERIFIED


# ==============================================================================
# 11. Legacy (không provider/quota_group — shape dispatch hiện tại) phải là model
#     Go trong catalog đang cấu hình, không thì không promote.
# ==============================================================================

@pytest.mark.parametrize(
    "model",
    [
        "deepseek-v4.1-flash",
        "opencode-go/deepseek-v4.1-flash",
        "glm-5.3-flash",
        "opencode-go/glm-5.3-flash:max",
        "deepseek-v4.1-flash-free",
    ],
)
def test_legacy_known_go_model_promotes(model):
    ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    records = [{"vendor": "opencode", "model": model, "status": "ok", "ts": ts}]
    res = evaluate_auth_evidence(records, "opencode", NOW, provider="opencode-go")
    assert res["authed"] is True


@pytest.mark.parametrize(
    "model",
    ["x-ai/grok-4", "openai/gpt-4o", "claude-3-5-sonnet", "some-random-model", "", 42, None],
)
def test_legacy_foreign_or_missing_model_does_not_promote(model):
    ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    record = {"vendor": "opencode", "status": "ok", "ts": ts}
    if model is not None:
        record["model"] = model
    res = evaluate_auth_evidence([record], "opencode", NOW, provider="opencode-go")
    assert res["authed"] is None
    assert res["reason"] == "no_evidence"


def test_legacy_foreign_model_does_not_promote_in_detect(monkeypatch):
    monkeypatch.setattr("doctor.write_state", lambda s, path=None: path)
    ts = (NOW_DT - timedelta(minutes=5)).isoformat()
    records = [{"vendor": "opencode", "model": "x-ai/grok-4", "status": "ok", "ts": ts}]
    p = detect(
        REGISTRY["opencode"],
        which=fake_which("/fake/home/.opencode/bin/opencode"),
        runner=fake_runner_ok,
        records=records,
        now=NOW,
    )
    assert p.authed is None
    assert classify(p) == VendorState.AUTH_UNVERIFIED


def test_ttl_constant_unchanged_one_hour():
    assert AUTH_PROBE_TTL == timedelta(hours=1)
