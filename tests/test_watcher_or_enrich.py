"""OR free-model enrichment: fetch OK → set models; fetch fail → giữ baseline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "bin"))

import lib.watcher as watcher


def test_enrich_sets_models_on_fetch_ok():
    snap = {"openrouter": {"models": [], "version": None, "state": "ready", "error": None}}
    watcher.enrich_openrouter_models(snap, fetcher=lambda: ["a/x:free", "b/y:free"])
    assert snap["openrouter"]["models"] == ["a/x:free", "b/y:free"]


def test_enrich_keeps_baseline_on_fetch_fail(tmp_path, monkeypatch):
    baseline = tmp_path / "watch-baseline.json"
    watcher.save_json(baseline, {"openrouter": {"models": ["old/model:free"]}})
    monkeypatch.setattr(watcher, "baseline_path", lambda: baseline)
    snap = {"openrouter": {"models": [], "version": None, "state": "ready", "error": None}}
    watcher.enrich_openrouter_models(snap, fetcher=lambda: None)
    # Fetch fail → carry-over từ baseline, KHÔNG phải [] (tránh alert giả 'removed')
    assert snap["openrouter"]["models"] == ["old/model:free"]


def test_enrich_noop_without_openrouter_vendor():
    snap = {"codex": {"models": ["gpt-5.5"], "version": "1", "state": "ready", "error": None}}
    watcher.enrich_openrouter_models(snap, fetcher=lambda: ["a/x:free"])
    assert "openrouter" not in snap
