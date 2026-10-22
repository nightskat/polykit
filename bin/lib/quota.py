from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import re

@dataclass(frozen=True)
class CapInfo:
    vendor: str
    reset_hint: str | None
    timezone: str | None = None

CAP_PATTERNS: list[tuple[str, str]] = [
    ("claude", r"usage limit reached"),
    ("claude", r"\d+-hour limit reached"),
    ("claude", r"limit will reset"),
    ("gemini", r"RESOURCE_EXHAUSTED"),
    ("gemini", r"resource has been exhausted"),
    ("codex", r"rate limit reached"),
    # Generic cap có NGỮ CẢNH quota/rate (Codex #5) — tránh bare number.
    ("unknown", r"quota exceeded"),
    ("unknown", r"exceeded your current quota"),
    ("unknown", r"too many requests"),
    # 429 CHỈ khi đứng cạnh từ ngữ cap (Codex #4) — không match "order id 429".
    ("unknown", r"429[^0-9].{0,40}(?:too many|rate|quota|exhaust|limit)"),
    ("unknown", r"(?:too many|rate|quota|exhaust|limit).{0,40}\b429\b"),
]

# ---------------------------------------------------------------------------
# 3-window Quota Constants & Evaluation (5h, weekly, monthly)
# ---------------------------------------------------------------------------

STANDARD_WINDOWS = ("5h", "weekly", "monthly")
WINDOW_KEY_ALIASES: dict[str, str] = {
    "5h": "5h",
    "5_hour": "5h",
    "5hour": "5h",
    "five_hour": "5h",
    "rolling_5h": "5h",
    "weekly": "weekly",
    "week": "weekly",
    "7d": "weekly",
    "monthly": "monthly",
    "month": "monthly",
    "30d": "monthly",
}

CAP_STATUSES = frozenset({"capped", "cap", "limit_reached", "exceeded", "exhausted", "quota_capped", "429"})
OK_STATUSES = frozenset({"ok", "healthy", "ready", "available", "good"})
UNKNOWN_STATUSES = frozenset({"unknown", "missing", "none", ""})


def normalize_window_status(val: Any) -> tuple[str, str | None]:
    """Chuẩn hóa trạng thái cửa sổ: ('capped' | 'ok' | 'unknown', reset_at | None).

    Dữ liệu thiếu hoặc không hợp lệ -> 'unknown' (không bịa healthy hay reset TTL).
    """
    if val is None:
        return "unknown", None

    if isinstance(val, str):
        v = val.strip().lower()
        if v in CAP_STATUSES:
            return "capped", None
        if v in OK_STATUSES:
            return "ok", None
        return "unknown", None

    if isinstance(val, (int, float)):
        if val >= 100:
            return "capped", None
        if 0 <= val < 100:
            return "ok", None
        return "unknown", None

    if isinstance(val, dict):
        status_val = val.get("status")
        reset_at = val.get("reset_at")
        if isinstance(reset_at, str):
            reset_at = reset_at.strip() or None
        else:
            reset_at = None

        if status_val is not None:
            st, _ = normalize_window_status(status_val)
            if st != "unknown":
                return st, reset_at

        # Kiểm tra qua các trường đo lường số nếu không có status tường minh
        pct = val.get("pct") or val.get("percentage")
        if pct is not None and isinstance(pct, (int, float)):
            if pct >= 100:
                return "capped", reset_at
            if 0 <= pct < 100:
                return "ok", reset_at

        used = val.get("used")
        limit = val.get("limit")
        if used is not None and limit is not None and isinstance(used, (int, float)) and isinstance(limit, (int, float)):
            if limit > 0 and used >= limit:
                return "capped", reset_at
            if limit > 0 and 0 <= used < limit:
                return "ok", reset_at

        remaining = val.get("remaining")
        if remaining is not None and isinstance(remaining, (int, float)):
            if remaining <= 0:
                return "capped", reset_at
            if remaining > 0:
                return "ok", reset_at

        return "unknown", reset_at

    return "unknown", None


def evaluate_quota_windows(windows: dict | list | None) -> dict[str, Any]:
    """Hàm thuần đánh giá 3 cửa sổ: 5h, weekly, monthly.

    Quy tắc:
    - Bất kỳ cửa sổ nào bị capped -> chặn group (status='capped', is_capped=True, blocked=True).
    - Dữ liệu thiếu/sai định dạng -> 'unknown' (không bịa healthy, không bịa reset TTL).
    - Chỉ khi CẢ 3 cửa sổ đầy đủ và ok -> status='ok' (healthy).
    - Không coi harness đổi là reset.
    """
    if not isinstance(windows, (dict, list)):
        return {
            "status": "unknown",
            "is_capped": False,
            "blocked": False,
            "capped_windows": [],
            "unknown_windows": list(STANDARD_WINDOWS),
            "ok_windows": [],
            "windows": {w: {"status": "unknown", "reset_at": None} for w in STANDARD_WINDOWS},
            "reset_at": None,
            "reason": "Missing or invalid windows data container (unknown)",
        }

    norm_input: dict[str, Any] = {}
    if isinstance(windows, dict):
        for k, v in windows.items():
            if isinstance(k, str):
                canonical_k = WINDOW_KEY_ALIASES.get(k.strip().lower())
                if canonical_k:
                    norm_input[canonical_k] = v
    elif isinstance(windows, list):
        for item in windows:
            if isinstance(item, dict):
                name = item.get("name") or item.get("window")
                if isinstance(name, str):
                    canonical_k = WINDOW_KEY_ALIASES.get(name.strip().lower())
                    if canonical_k:
                        norm_input[canonical_k] = item

    parsed_windows: dict[str, dict[str, Any]] = {}
    capped_windows: list[str] = []
    unknown_windows: list[str] = []
    ok_windows: list[str] = []
    discovered_reset_at: str | None = None

    for w in STANDARD_WINDOWS:
        if w not in norm_input:
            parsed_windows[w] = {"status": "unknown", "reset_at": None}
            unknown_windows.append(w)
            continue

        raw_val = norm_input[w]
        st, r_at = normalize_window_status(raw_val)
        parsed_windows[w] = {"status": st, "reset_at": r_at}

        if st == "capped":
            capped_windows.append(w)
            if r_at and discovered_reset_at is None:
                discovered_reset_at = r_at
        elif st == "ok":
            ok_windows.append(w)
        else:
            unknown_windows.append(w)

    if capped_windows:
        return {
            "status": "capped",
            "is_capped": True,
            "blocked": True,
            "capped_windows": capped_windows,
            "unknown_windows": unknown_windows,
            "ok_windows": ok_windows,
            "windows": parsed_windows,
            "reset_at": discovered_reset_at,
            "reason": f"Quota window capped: {', '.join(capped_windows)}",
        }

    if unknown_windows:
        return {
            "status": "unknown",
            "is_capped": False,
            "blocked": False,
            "capped_windows": [],
            "unknown_windows": unknown_windows,
            "ok_windows": ok_windows,
            "windows": parsed_windows,
            "reset_at": None,
            "reason": f"Incomplete quota window data; missing or unknown: {', '.join(unknown_windows)}",
        }

    return {
        "status": "ok",
        "is_capped": False,
        "blocked": False,
        "capped_windows": [],
        "unknown_windows": [],
        "ok_windows": ok_windows,
        "windows": parsed_windows,
        "reset_at": None,
        "reason": "All 3 quota windows are healthy",
    }


evaluate_windows = evaluate_quota_windows


def detect_cap(stderr: str, vendor_hint: str | None = None) -> CapInfo | None:
    matched_vendor = None
    for vendor, pattern in CAP_PATTERNS:
        if re.search(pattern, stderr, re.IGNORECASE | re.DOTALL):
            matched_vendor = vendor
            break

    if matched_vendor is None:
        return None

    vendor = vendor_hint if vendor_hint is not None else matched_vendor

    # reset_hint CHỈ là mốc thời gian (Codex #3) — timezone tách field riêng.
    reset_match = re.search(
        r"reset(?:s| at)?\s+(?:at\s+)?([0-9]{1,2}\s*[ap]m|[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?|[0-9]{4}-[0-9]{2}-[0-9T:\-Z]+)",
        stderr,
        re.IGNORECASE,
    )
    reset_hint = reset_match.group(1).strip() if reset_match else None
    tz_match = re.search(r"\b([A-Za-z_]+/[A-Za-z_]+)\b", stderr)
    tz = tz_match.group(1) if tz_match else None

    return CapInfo(vendor=vendor, reset_hint=reset_hint, timezone=tz)

def classify_signal(stderr: str = "", pressure_pct: int | None = None, threshold: int = 80, vendor_hint: str | None = None) -> str:
    if detect_cap(stderr, vendor_hint):
        return "cap"
    # Codex #1: stderr lạ (không phải cap) đứng TRƯỚC pressure — không cho một
    # lỗi không rõ nguồn kích hoạt ping proactive. Pressure hợp lệ đến từ cron
    # quota-check (chỉ truyền pressure_pct, không kèm stderr).
    if stderr.strip():
        return "unknown"
    if pressure_pct is not None and pressure_pct >= threshold:
        return "pressure"
    return "none"

def should_warn_pressure(pct: int | None, threshold: int = 80) -> bool:
    return pct is not None and pct >= threshold
