import pytest
from pathlib import Path
from bin.failover import handle_signal

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")

class MockNotifier:
    def __init__(self):
        self.calls = []
        
    def __call__(self, message: str, silent: bool = False) -> bool:
        self.calls.append(message)
        return True

def test_failover_routing_cap():
    stderr = read_fixture("claude_cap.txt")
    notifier = MockNotifier()
    
    res = handle_signal(stderr=stderr, notifier=notifier)
    
    assert res["action"] == "ping_reactive"
    assert res["signal"] == "cap"
    assert "codex main" in res["message"]
    assert len(notifier.calls) == 1
    assert "codex main" in notifier.calls[0]

def test_failover_routing_pressure():
    notifier = MockNotifier()
    
    res = handle_signal(pressure_pct=90, notifier=notifier)
    
    assert res["action"] == "ping_proactive"
    assert res["signal"] == "pressure"
    assert "Handoff" in res["message"]
    assert len(notifier.calls) == 1
    assert "Handoff" in notifier.calls[0]

def test_failover_routing_unknown():
    stderr = read_fixture("unknown_error.txt")
    notifier = MockNotifier()
    logged_errors = []
    
    def mock_logger(msg):
        logged_errors.append(msg)
        
    res = handle_signal(stderr=stderr, notifier=notifier, logger=mock_logger)
    
    assert res["action"] == "log_silent"
    assert res["signal"] == "unknown"
    assert len(notifier.calls) == 0
    assert len(logged_errors) == 1
    assert stderr in logged_errors[0]

def test_failover_routing_none():
    notifier = MockNotifier()

    res = handle_signal(stderr="", pressure_pct=50, notifier=notifier)

    assert res["action"] == "noop"
    assert res["signal"] == "none"
    assert len(notifier.calls) == 0


def test_unknown_stderr_suppresses_pressure_ping():
    """Codex #1: lỗi lạ + pressure cao → KHÔNG ping (error lạ tuyệt đối không ping)."""
    notifier = MockNotifier()
    res = handle_signal(stderr="ConnectionResetError boom", pressure_pct=95, notifier=notifier)
    assert res["action"] == "log_silent"
    assert len(notifier.calls) == 0


def test_notifier_exception_does_not_crash():
    """Codex #2: notifier raise → handle_signal vẫn trả kết quả, notified=False."""
    def boom(msg, silent=False):
        raise RuntimeError("tg down")
    res = handle_signal(pressure_pct=90, notifier=boom)
    assert res["action"] == "ping_proactive"
    assert res["notified"] is False


def test_429_bare_number_not_false_cap():
    """Codex #4: '429' trong ngữ cảnh thường KHÔNG bị coi là cap."""
    notifier = MockNotifier()
    res = handle_signal(stderr="order id 429 processed ok", notifier=notifier)
    assert res["signal"] == "unknown"
    assert len(notifier.calls) == 0
