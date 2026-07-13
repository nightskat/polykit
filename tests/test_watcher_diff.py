import pytest
from lib.watcher import diff_snapshots, changes_hash, is_offline

def test_diff_snapshots_empty_baseline():
    old = {}
    new = {
        "codex": {"models": ["model-a"], "version": "1.0", "state": "ready"}
    }
    assert diff_snapshots(old, new) == []

def test_diff_snapshots_version_changed():
    old = {
        "codex": {"models": ["model-a"], "version": "1.0", "state": "ready"}
    }
    new = {
        "codex": {"models": ["model-a"], "version": "1.1", "state": "ready"}
    }
    diff = diff_snapshots(old, new)
    assert len(diff) == 1
    assert diff[0] == {"vendor": "codex", "type": "version", "old": "1.0", "new": "1.1"}

def test_diff_snapshots_models_changed():
    old = {
        "codex": {"models": ["model-a"], "version": "1.0", "state": "ready"}
    }
    new = {
        "codex": {"models": ["model-a", "model-b"], "version": "1.0", "state": "ready"}
    }
    diff = diff_snapshots(old, new)
    assert len(diff) == 1
    assert diff[0] == {"vendor": "codex", "type": "models", "added": ["model-b"], "removed": []}

    # Model removed
    new_removed = {
        "codex": {"models": [], "version": "1.0", "state": "ready"}
    }
    diff_rem = diff_snapshots(old, new_removed)
    assert len(diff_rem) == 1
    assert diff_rem[0] == {"vendor": "codex", "type": "models", "added": [], "removed": ["model-a"]}

def test_diff_snapshots_state_changed():
    old = {
        "claude": {"models": [], "version": "1.0", "state": "ready"}
    }
    new = {
        "claude": {"models": [], "version": "1.0", "state": "not_authed"}
    }
    diff = diff_snapshots(old, new)
    assert len(diff) == 1
    assert diff[0] == {"vendor": "claude", "type": "state", "old": "ready", "new": "not_authed"}

def test_diff_snapshots_no_change():
    old = {
        "codex": {"models": ["model-a"], "version": "1.0", "state": "ready"}
    }
    new = {
        "codex": {"models": ["model-a"], "version": "1.0", "state": "ready"}
    }
    assert diff_snapshots(old, new) == []

def test_changes_hash_stable():
    changes1 = [
        {"vendor": "codex", "type": "version", "old": "1.0", "new": "1.1"},
        {"vendor": "claude", "type": "state", "old": "ready", "new": "not_authed"}
    ]
    changes2 = [
        {"vendor": "claude", "type": "state", "old": "ready", "new": "not_authed"},
        {"vendor": "codex", "type": "version", "old": "1.0", "new": "1.1"}
    ]
    assert changes_hash(changes1) == changes_hash(changes2)
    
    changes3 = [
        {"vendor": "codex", "type": "version", "old": "1.0", "new": "1.2"}
    ]
    assert changes_hash(changes1) != changes_hash(changes3)

def test_is_offline():
    assert is_offline({}) is True

    # Codex M4 #2: offline = mọi vendor có error (detect fail), KHÔNG phải not_installed.
    offline_snap = {
        "claude": {"models": [], "version": None, "state": "not_installed", "error": "timeout"},
        "gemini": {"models": [], "version": None, "state": "not_installed", "error": "timeout"},
    }
    assert is_offline(offline_snap) is True

    # Gỡ vendor thật (not_installed, error=None) KHÔNG phải offline.
    removed_snap = {
        "claude": {"models": [], "version": None, "state": "not_installed", "error": None},
        "gemini": {"models": [], "version": None, "state": "not_installed", "error": None},
    }
    assert is_offline(removed_snap) is False

    online_snap = {
        "claude": {"models": [], "version": "1.0", "state": "ready", "error": None},
        "gemini": {"models": [], "version": "1.0", "state": "not_installed", "error": None},
    }
    assert is_offline(online_snap) is False
