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
    r"usage limit reached"
]

def is_quota_error(stderr: str, returncode: int | None = None) -> bool:
    if returncode == 402:
        return True
    for pattern in QUOTA_ERROR_PATTERNS:
        if re.search(pattern, stderr, re.IGNORECASE):
            return True
    return False
