import pytest
from pathlib import Path
from bin.lib.quota import detect_cap, classify_signal

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")

def test_claude_cap():
    stderr = read_fixture("claude_cap.txt")
    cap = detect_cap(stderr)
    assert cap is not None
    assert cap.vendor == "claude"
    assert cap.reset_hint is not None
    assert "3pm" in cap.reset_hint
    
    sig = classify_signal(stderr=stderr)
    assert sig == "cap"

def test_claude_cap_5h():
    stderr = read_fixture("claude_cap_5h.txt")
    cap = detect_cap(stderr)
    assert cap is not None
    assert cap.vendor == "claude"
    assert cap.reset_hint is not None
    assert "3pm" in cap.reset_hint
    
    sig = classify_signal(stderr=stderr)
    assert sig == "cap"

def test_gemini_quota():
    stderr = read_fixture("gemini_quota.txt")
    cap = detect_cap(stderr)
    assert cap is not None
    assert cap.vendor in ("gemini", "unknown")
    sig = classify_signal(stderr=stderr)
    assert sig == "cap"

def test_codex_ratelimit():
    stderr = read_fixture("codex_ratelimit.txt")
    cap = detect_cap(stderr)
    assert cap is not None
    assert cap.vendor in ("codex", "unknown")
    sig = classify_signal(stderr=stderr)
    assert sig == "cap"

def test_unknown_error():
    stderr = read_fixture("unknown_error.txt")
    cap = detect_cap(stderr)
    assert cap is None
    
    sig = classify_signal(stderr=stderr)
    assert sig == "unknown"

def test_classify_signal_pressure():
    assert classify_signal(pressure_pct=85) == "pressure"
    assert classify_signal(pressure_pct=50) == "none"
    assert classify_signal(pressure_pct=80) == "pressure"
    assert classify_signal(pressure_pct=None) == "none"

def test_classify_signal_empty():
    assert classify_signal() == "none"
    assert classify_signal(stderr="   ") == "none"
