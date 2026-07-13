import os
import pytest
from lib.dispatch_core import DispatchError, validate_timeout, validate_sandbox
from lib.dispatcher import run_vendor

def test_validate_timeout():
    # Valid cases
    assert validate_timeout(1) == 1
    assert validate_timeout("120") == 120
    assert validate_timeout(600) == 600

    # Invalid cases
    with pytest.raises(DispatchError):
        validate_timeout(0)
    with pytest.raises(DispatchError):
        validate_timeout(601)
    with pytest.raises(DispatchError):
        validate_timeout("abc")
    with pytest.raises(DispatchError):
        validate_timeout(-10)

def test_validate_sandbox():
    # Valid cases
    assert validate_sandbox("read-only") == "read-only"
    assert validate_sandbox("workspace-write") == "workspace-write"

    # Invalid cases
    with pytest.raises(DispatchError):
        validate_sandbox("write")
    with pytest.raises(DispatchError):
        validate_sandbox("")
    with pytest.raises(DispatchError):
        validate_sandbox("workspace-read")

def test_depth_guard_blocked(monkeypatch):
    # Set dispatch depth to 3
    monkeypatch.setenv("XCLI_DISPATCH_DEPTH", "3")
    
    result = run_vendor("codex", "test prompt")
    assert result.status == "blocked"
    assert "depth" in result.summary
    assert "possible loop" in result.summary

def test_empty_prompt_blocked():
    result = run_vendor("codex", "")
    assert result.status == "blocked"
    assert "Empty prompt" in result.summary

    result = run_vendor("codex", "   \n  \t ")
    assert result.status == "blocked"
    assert "Empty prompt" in result.summary
