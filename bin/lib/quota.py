from __future__ import annotations
from dataclasses import dataclass
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
