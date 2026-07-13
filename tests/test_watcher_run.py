import pytest
from pathlib import Path
from watcher import run_watch
import lib.watcher as watcher

@pytest.fixture(autouse=True)
def setup_tmp_paths(tmp_path, monkeypatch):
    base_p = tmp_path / "baseline.json"
    alert_p = tmp_path / "alert.json"
    lock_p = tmp_path / "lock.d"
    
    monkeypatch.setattr(watcher, "baseline_path", lambda: base_p)
    monkeypatch.setattr(watcher, "alert_state_path", lambda: alert_p)
    monkeypatch.setattr(watcher, "lock_path", lambda: lock_p)

def test_watcher_acceptance_bump_1_alert():
    # 1. Baseline có codex version A
    state_a = {
        "vendors": {
            "codex": {
                "state": "ready",
                "cli_version": "A",
                "models": ["model-1"]
            }
        }
    }
    
    # Giả lập chạy run_watch lần đầu để lưu baseline A (diff rỗng)
    res = run_watch(state=state_a)
    assert res["action"] == "noop"
    assert res["reason"] == "no_change"
    
    # 2. Chạy run_watch với state codex version B -> action alert, notifier 1 lần
    state_b = {
        "vendors": {
            "codex": {
                "state": "ready",
                "cli_version": "B",
                "models": ["model-1"]
            }
        }
    }
    
    notifier_calls = []
    def mock_notifier(msg):
        notifier_calls.append(msg)
        return True

    res2 = run_watch(state=state_b, notifier=mock_notifier)
    assert res2["action"] == "alert"
    assert len(notifier_calls) == 1
    assert "version A→B" in res2["message"]
    
    # 3. Chạy lại cùng state B -> do baseline đã lưu là B, chạy trực tiếp sẽ trả về no_change (0 alert).
    # Nhưng để chứng minh tính năng dedup bằng hash (h == last), ta đặt baseline lùi lại A.
    # Khi đó diff giữa baseline (A) và state (B) vẫn tạo ra thay đổi, nhưng vì hash trùng, 
    # nó sẽ nhận ra đã alert rồi -> trả về already_alerted và 0 alert.
    watcher.save_json(watcher.baseline_path(), watcher.snapshot_from_state(state_a))
    res3 = run_watch(state=state_b, notifier=mock_notifier)
    assert res3["action"] == "noop"
    assert res3["reason"] == "already_alerted"
    assert len(notifier_calls) == 1  # Không đổi, vẫn là 1

def test_watcher_offline():
    # Set baseline A
    state_a = {
        "vendors": {
            "codex": {
                "state": "ready",
                "cli_version": "A",
                "models": ["model-1"]
            }
        }
    }
    run_watch(state=state_a)

    # Offline THẬT = detect fail hạ tầng: mọi vendor có error (Codex M4 #2).
    state_offline = {
        "vendors": {
            "codex": {"state": "not_installed", "cli_version": None, "models": [], "error": "timeout"},
            "claude": {"state": "not_installed", "cli_version": None, "models": [], "error": "timeout"},
        }
    }

    notifier_calls = []
    def mock_notifier(msg):
        notifier_calls.append(msg)
        return True

    res = run_watch(state=state_offline, notifier=mock_notifier)
    assert res["action"] == "noop"
    assert res["reason"] == "offline"
    assert len(notifier_calls) == 0

    # baseline không đổi (vẫn là version A)
    snap = watcher.load_json(watcher.baseline_path())
    assert snap["codex"]["version"] == "A"


def test_genuine_removal_not_offline():
    """Codex M4 #2: gỡ vendor thật (not_installed, KHÔNG error) ≠ offline —
    phải báo disappeared, không mù vĩnh viễn."""
    state_a = {"vendors": {
        "codex": {"state": "ready", "cli_version": "A", "models": ["m1"], "error": None},
        "claude": {"state": "ready", "cli_version": "2.1", "models": [], "error": None},
    }}
    run_watch(state=state_a)
    # codex bị gỡ thật (not_installed, error=None)
    state_removed = {"vendors": {
        "codex": {"state": "not_installed", "cli_version": None, "models": [], "error": None},
        "claude": {"state": "ready", "cli_version": "2.1", "models": [], "error": None},
    }}
    calls = []
    res = run_watch(state=state_removed, notifier=lambda m: calls.append(m) or True)
    assert res["action"] == "alert"
    assert len(calls) == 1

def test_watcher_notifier_raise():
    # Set baseline A
    state_a = {
        "vendors": {
            "codex": {
                "state": "ready",
                "cli_version": "A",
                "models": ["model-1"]
            }
        }
    }
    run_watch(state=state_a)
    
    # Thay đổi sang B để kích hoạt notifier
    state_b = {
        "vendors": {
            "codex": {
                "state": "ready",
                "cli_version": "B",
                "models": ["model-1"]
            }
        }
    }
    
    def raising_notifier(msg):
        raise RuntimeError("Network down")
        
    res = run_watch(state=state_b, notifier=raising_notifier)
    assert res["action"] == "alert"
    assert res["notified"] is False
