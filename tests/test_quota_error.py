import pytest
from bin.lib.quota_error import is_quota_error

def test_is_quota_error_cases():
    assert is_quota_error("HTTP 402 Payment Required") is True
    assert is_quota_error("insufficient credit") is True
    assert is_quota_error("out of credits") is True
    assert is_quota_error("RESOURCE_EXHAUSTED") is True
    assert is_quota_error("normal output, all good") is False
    assert is_quota_error("order 402abc") is False
    assert is_quota_error("connection reset") is False
    # Codex M2 #1: 402 rời ngữ cảnh KHÔNG được coi là quota.
    assert is_quota_error("order 402 failed to ship") is False
    assert is_quota_error("code=402; invalid input") is True  # có 'code' → quota
    assert is_quota_error("status: 402") is True

def test_is_quota_error_returncode():
    assert is_quota_error("some error", returncode=402) is True
    assert is_quota_error("some error", returncode=500) is False
