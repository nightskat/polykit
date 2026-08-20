from __future__ import annotations
import re

QUOTA_ERROR_PATTERNS: list[str] = [
    # 402 CHỈ khi có ngữ cảnh HTTP/status (Codex M2 #1) — không nuốt "order 402 failed".
    r"(?:HTTP|status|code|error)\s*[:=]?\s*402\b",
    r"payment required",
    r"insufficient (?:credit|balance|funds)",
    r"out of credits?",
    r"quota exceeded",
    r"resource has been exhausted",
    r"RESOURCE_EXHAUSTED",
    r"rate limit reached",
    r"usage limit reached",
    # Đo thật 20/08/2026 — codex CLI in NGUYÊN VĂN "You've hit your usage limit",
    # không khớp "usage limit reached" ở trên. Thiếu mẫu này thì hết quota bị xếp
    # nhầm thành vendor_exit_nonzero và failover đi sai nhánh (BUG-5).
    r"hit your usage limit",
    # gemini-cli: "You have exhausted your daily quota on this model."
    r"exhausted your (?:daily )?quota",
]

def is_quota_error(stderr: str, returncode: int | None = None) -> bool:
    if returncode == 402:
        return True
    for pattern in QUOTA_ERROR_PATTERNS:
        if re.search(pattern, stderr, re.IGNORECASE):
            return True
    return False
