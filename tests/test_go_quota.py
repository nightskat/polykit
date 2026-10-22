"""Tests for OpenCode Go 3-window quota, shared quota group (hermes/opencode),
evidence retention, failover candidate filtering, and policy enforcement.
"""
from datetime import datetime, timedelta, timezone
import pytest

from bin.lib.quota import (
    evaluate_quota_windows,
    evaluate_windows,
    normalize_window_status,
    detect_cap,
    classify_signal,
)
from bin.lib.doctor_quota import (
    quota_capped_since,
    window_for,
    is_go_vendor,
    is_free_record,
    is_full_window_snapshot_healthy,
)
from bin.failover import (
    handle_signal,
    filter_failover_candidates,
)

NOW = "2026-10-22T12:00:00+00:00"
NOW_DT = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


class MockNotifier:
    """Mock notifier for testing without sending real Telegram alerts."""
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, message: str, silent: bool = False) -> bool:
        self.calls.append(message)
        return True


# ===========================================================================
# 1. Hàm thuần đánh giá 3 cửa sổ: 5h, weekly, monthly
# ===========================================================================

def test_evaluate_3_windows_5h_capped():
    """Bất kỳ cửa sổ nào bị capped (5h) -> chặn group."""
    windows = {
        "5h": "capped",
        "weekly": "ok",
        "monthly": "ok",
    }
    res = evaluate_quota_windows(windows)
    assert res["status"] == "capped"
    assert res["is_capped"] is True
    assert res["blocked"] is True
    assert res["capped_windows"] == ["5h"]


def test_evaluate_3_windows_weekly_capped():
    """Bất kỳ cửa sổ nào bị capped (weekly) -> chặn group."""
    windows = {
        "5h": {"status": "ok"},
        "weekly": {"status": "capped", "reset_at": "2026-10-25T00:00:00Z"},
        "monthly": {"status": "ok"},
    }
    res = evaluate_quota_windows(windows)
    assert res["status"] == "capped"
    assert res["is_capped"] is True
    assert res["blocked"] is True
    assert res["capped_windows"] == ["weekly"]
    assert res["reset_at"] == "2026-10-25T00:00:00Z"


def test_evaluate_3_windows_monthly_capped():
    """Bất kỳ cửa sổ nào bị capped (monthly) -> chặn group."""
    windows = {
        "5h": 50,  # 50% -> ok
        "weekly": 80,  # 80% -> ok
        "monthly": {"used": 1000, "limit": 1000},  # used >= limit -> capped
    }
    res = evaluate_windows(windows)
    assert res["status"] == "capped"
    assert res["is_capped"] is True
    assert res["blocked"] is True
    assert res["capped_windows"] == ["monthly"]


def test_evaluate_3_windows_all_healthy():
    """Chỉ khi cả 3 cửa sổ đều ok -> status='ok' (healthy)."""
    windows = {
        "5h": "ok",
        "weekly": "ok",
        "monthly": "ok",
    }
    res = evaluate_quota_windows(windows)
    assert res["status"] == "ok"
    assert res["is_capped"] is False
    assert res["blocked"] is False
    assert len(res["ok_windows"]) == 3
    assert len(res["capped_windows"]) == 0
    assert len(res["unknown_windows"]) == 0


def test_evaluate_3_windows_missing_is_unknown():
    """Dữ liệu thiếu là unknown không bịa healthy/reset TTL."""
    windows = {
        "5h": "ok",
        # Thiếu weekly và monthly
    }
    res = evaluate_quota_windows(windows)
    assert res["status"] == "unknown"
    assert res["is_capped"] is False
    assert res["blocked"] is False
    assert "weekly" in res["unknown_windows"]
    assert "monthly" in res["unknown_windows"]
    assert res["reset_at"] is None  # Không bịa reset TTL


def test_evaluate_3_windows_invalid_data_is_unknown():
    """Dữ liệu sai định dạng/lạ -> unknown, không coi là ok."""
    windows = {
        "5h": "ok",
        "weekly": "invalid_gibberish_status",
        "monthly": "ok",
    }
    res = evaluate_quota_windows(windows)
    assert res["status"] == "unknown"
    assert res["is_capped"] is False
    assert "weekly" in res["unknown_windows"]


def test_evaluate_3_windows_none_input_is_unknown():
    """None hoặc container rỗng -> unknown toàn bộ."""
    res = evaluate_quota_windows(None)
    assert res["status"] == "unknown"
    assert res["is_capped"] is False
    assert len(res["unknown_windows"]) == 3


def test_evaluate_3_windows_capped_beats_unknown():
    """Nếu có ít nhất 1 cửa sổ capped, dù có cửa sổ khác unknown vẫn chặn group."""
    windows = {
        "5h": "capped",
        "weekly": "unknown",
        "monthly": "ok",
    }
    res = evaluate_quota_windows(windows)
    assert res["status"] == "capped"
    assert res["is_capped"] is True
    assert res["blocked"] is True
    assert res["capped_windows"] == ["5h"]


# ===========================================================================
# 2. Quota Group opencode-go dùng chung hermes và opencode
# ===========================================================================

def test_shared_quota_group_opencode_cap_blocks_hermes():
    """Cap trên opencode chặn cả opencode và hermes trong quota_capped_since."""
    cap_ts = "2026-10-22T10:00:00+00:00"
    records = [{"vendor": "opencode", "status": "quota_capped", "ts": cap_ts}]
    res = quota_capped_since(records, NOW)
    assert "opencode" in res
    assert "hermes" in res
    assert res["opencode"] == cap_ts
    assert res["hermes"] == cap_ts


def test_shared_quota_group_hermes_cap_blocks_opencode():
    """Cap trên hermes chặn cả hermes và opencode trong quota_capped_since."""
    cap_ts = "2026-10-22T10:00:00+00:00"
    records = [{"vendor": "hermes", "status": "quota_capped", "ts": cap_ts}]
    res = quota_capped_since(records, NOW)
    assert "hermes" in res
    assert "opencode" in res
    assert res["hermes"] == cap_ts
    assert res["opencode"] == cap_ts


def test_harness_switch_does_not_reset_quota_group():
    """Không coi harness đổi là reset: opencode cap rồi hermes gọi ok đơn lẻ KHÔNG xoá cap."""
    records = [
        {"vendor": "opencode", "status": "quota_capped", "ts": "2026-10-22T09:00:00+00:00"},
        {"vendor": "hermes", "status": "ok", "ts": "2026-10-22T10:00:00+00:00"},
    ]
    res = quota_capped_since(records, NOW)
    assert "opencode" in res
    assert "hermes" in res


# ===========================================================================
# 3. Go cap evidence: không tự xanh sau default 5h & giữ cap tới reset_at / snapshot
# ===========================================================================

def test_go_cap_does_not_auto_green_after_default_5h():
    """Go cap evidence KHÔNG tự xanh sau default 5h (khác legacy codex)."""
    old_cap_ts = "2026-10-22T04:00:00+00:00"  # 8 giờ trước NOW (vượt 5h)
    records = [{"vendor": "opencode", "status": "quota_capped", "ts": old_cap_ts}]
    res = quota_capped_since(records, NOW)
    # Vẫn bị capped sau 8h vì Go không tự reset sau 5h
    assert "opencode" in res
    assert "hermes" in res


def test_go_cap_clears_on_verified_reset_at():
    """Go cap xoá khi tới reset_at đã xác minh trong quá khứ."""
    cap_ts = "2026-10-22T08:00:00+00:00"
    reset_at_past = "2026-10-22T11:00:00+00:00"  # 1h trước NOW (đã qua)
    records = [{
        "vendor": "opencode",
        "status": "quota_capped",
        "ts": cap_ts,
        "reset_at": reset_at_past,
    }]
    res = quota_capped_since(records, NOW)
    assert "opencode" not in res
    assert "hermes" not in res


def test_go_cap_remains_active_if_reset_at_in_future():
    """Go cap giữ nguyên nếu reset_at ở tương lai."""
    cap_ts = "2026-10-22T10:00:00+00:00"
    reset_at_future = "2026-10-22T15:00:00+00:00"  # 3h sau NOW
    records = [{
        "vendor": "opencode",
        "status": "quota_capped",
        "ts": cap_ts,
        "reset_at": reset_at_future,
    }]
    res = quota_capped_since(records, NOW)
    assert "opencode" in res
    assert "hermes" in res


def test_free_model_success_does_not_clear_paid_monthly_cap():
    """Thành công của model free KHÔNG xoá paid monthly cap."""
    records = [
        {
            "vendor": "opencode",
            "status": "quota_capped",
            "ts": "2026-10-22T09:00:00+00:00",
            "model": "deepseek-v4.1-flash",
            "window": "monthly",
        },
        {
            "vendor": "opencode",
            "status": "ok",
            "ts": "2026-10-22T10:00:00+00:00",
            "model": "deepseek-v4.1-flash-free",
            "is_free": True,
        },
    ]
    res = quota_capped_since(records, NOW)
    assert "opencode" in res
    assert "hermes" in res


def test_different_model_success_does_not_clear_paid_monthly_cap():
    """Thành công khác model KHÔNG xoá paid monthly cap."""
    records = [
        {
            "vendor": "opencode",
            "status": "quota_capped",
            "ts": "2026-10-22T09:00:00+00:00",
            "model": "deepseek-v4.1-flash",
            "window": "monthly",
        },
        {
            "vendor": "opencode",
            "status": "ok",
            "ts": "2026-10-22T10:00:00+00:00",
            "model": "glm-5.3-flash",
        },
    ]
    res = quota_capped_since(records, NOW)
    assert "opencode" in res
    assert "hermes" in res


def test_single_ok_does_not_clear_go_cap_without_full_window_snapshot():
    """Không infer từ ok đơn lẻ: gọi đơn lẻ ok không xoá Go cap."""
    records = [
        {
            "vendor": "opencode",
            "status": "quota_capped",
            "ts": "2026-10-22T09:00:00+00:00",
            "model": "deepseek-v4.1-flash",
        },
        {
            "vendor": "opencode",
            "status": "ok",
            "ts": "2026-10-22T10:00:00+00:00",
            "model": "deepseek-v4.1-flash",
        },
    ]
    res = quota_capped_since(records, NOW)
    assert "opencode" in res
    assert "hermes" in res


def test_explicit_full_window_snapshot_healthy_clears_cap():
    """Explicit full-window snapshot healthy xoá cap."""
    records = [
        {
            "vendor": "opencode",
            "status": "quota_capped",
            "ts": "2026-10-22T09:00:00+00:00",
            "model": "deepseek-v4.1-flash",
        },
        {
            "vendor": "opencode",
            "status": "ok",
            "ts": "2026-10-22T10:00:00+00:00",
            "full_window_healthy": True,
            "windows": {
                "5h": "ok",
                "weekly": "ok",
                "monthly": "ok",
            },
        },
    ]
    res = quota_capped_since(records, NOW)
    assert "opencode" not in res
    assert "hermes" not in res


# ===========================================================================
# 4. Failover candidate filtering & Model Policy
# ===========================================================================

def test_failover_filters_same_quota_group():
    """Cap một harness không gợi ý harness kia (loại bỏ ứng viên cùng quota_group)."""
    candidates = ["hermes", "codex", "gemini"]
    filtered = filter_failover_candidates(candidates, vendor_hint="opencode")
    assert "hermes" not in filtered
    assert "codex" in filtered
    assert "gemini" in filtered


def test_failover_filters_free_models():
    """Failover source cấm model free (free chỉ được chọn tường minh qua --model)."""
    candidates = [
        "codex",
        "opencode-go/deepseek-v4.1-flash-free",
        {"vendor": "gemini", "model": "gemini-2.0-flash-free"},
    ]
    filtered = filter_failover_candidates(candidates, vendor_hint="claude")
    assert len(filtered) == 1
    assert filtered[0] == "codex"


def test_failover_filters_contributor_models():
    """Failover source cấm tuyệt đối model contributor (chính sách data training)."""
    candidates = [
        "codex",
        "gemini-4-argon-contributor",
        {"vendor": "agy", "model": "muse-spark-contributor"},
    ]
    filtered = filter_failover_candidates(candidates, vendor_hint="claude")
    assert len(filtered) == 1
    assert filtered[0] == "codex"


# ===========================================================================
# 5. Recommendation không auto dispatch / retry
# ===========================================================================

def test_failover_no_auto_dispatch_or_retry():
    """Recommendation là gợi ý, không auto dispatch hoặc retry."""
    notifier = MockNotifier()
    res = handle_signal(
        stderr="quota exceeded",
        vendor_hint="opencode",
        candidates=["hermes", "codex", "gemini"],
        notifier=notifier,
    )
    assert res["action"] == "ping_reactive"
    assert res["signal"] == "cap"
    assert res["auto_dispatch"] is False
    assert res["auto_retry"] is False
    assert "hermes" not in res["recommended_candidates"]
    assert "codex" in res["recommended_candidates"]
    assert len(notifier.calls) == 1
    assert "Không tự động dispatch" in notifier.calls[0] or "không tự động dispatch" in notifier.calls[0]


def test_failover_vision_sensitive_not_auto_dispatched():
    """Không dispatch vision/sensitive tự động."""
    notifier = MockNotifier()
    res = handle_signal(
        stderr="429 quota exceeded",
        vendor_hint="opencode",
        candidates=["codex", "gemini"],
        is_vision=True,
        is_sensitive=True,
        notifier=notifier,
    )
    assert res["auto_dispatch"] is False
    assert res["auto_retry"] is False


# ===========================================================================
# 6. Kết nối failover handle_signal với windows tùy chọn
# ===========================================================================

def test_handle_signal_with_windows_capped():
    """handle_signal với windows bị cap kích hoạt reactive ping."""
    notifier = MockNotifier()
    windows = {
        "5h": "ok",
        "weekly": "capped",
        "monthly": "ok",
    }
    res = handle_signal(
        windows=windows,
        vendor_hint="opencode",
        candidates=["hermes", "codex"],
        notifier=notifier,
    )
    assert res["action"] == "ping_reactive"
    assert res["signal"] == "cap"
    assert "weekly" in res["windows_evaluation"]["capped_windows"]
    assert len(notifier.calls) == 1
    assert "hermes" not in res["recommended_candidates"]


def test_handle_signal_with_windows_unknown_suppresses_ping():
    """handle_signal với windows dữ liệu thiếu -> unknown, không gửi ping nhảm."""
    notifier = MockNotifier()
    windows = {
        "5h": "ok",
        # Thiếu weekly/monthly
    }
    res = handle_signal(
        windows=windows,
        vendor_hint="opencode",
        notifier=notifier,
    )
    assert res["action"] == "log_silent"
    assert res["signal"] == "unknown"
    assert len(notifier.calls) == 0


# ===========================================================================
# 7. Legacy Vendor Contract Unbroken
# ===========================================================================

def test_legacy_vendor_contract_unbroken():
    """Vendor cũ (claude, codex, gemini, grok) giữ nguyên contract legacy."""
    # Codex hết hạn sau 5h
    assert window_for("codex") == timedelta(hours=5)
    # Gemini hết hạn sau 24h
    assert window_for("gemini") == timedelta(hours=24)
    # Grok không tự hết hạn
    assert window_for("grok") is None
    # Claude handle_signal không truyền candidates vẫn giữ message lane cũ
    notifier = MockNotifier()
    res = handle_signal(stderr="usage limit reached", notifier=notifier)
    assert res["action"] == "ping_reactive"
    assert "codex main" in res["message"]
    assert len(notifier.calls) == 1
