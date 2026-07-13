#!/usr/bin/env python3
from __future__ import annotations
import sys
import argparse
import json
from pathlib import Path

# Add bin and bin/lib to sys.path
bin_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(bin_dir))

from doctor import run_doctor
from lib.notifier import default_notifier
import lib.watcher as watcher

def run_watch(state=None, now=None, notifier=None, detector=None) -> dict:
    if notifier is None:
        notifier = default_notifier

    try:
        with watcher.WatchLock():
            if state is None:
                if detector is not None:
                    state = detector()
                else:
                    state = run_doctor(now=now)
            
            new_snap = watcher.snapshot_from_state(state)
            
            if watcher.is_offline(new_snap):
                return {"action": "noop", "reason": "offline"}
            
            old_snap = watcher.load_json(watcher.baseline_path())
            changes = watcher.diff_snapshots(old_snap, new_snap)
            
            if not changes:
                watcher.save_json(watcher.baseline_path(), new_snap)
                return {"action": "noop", "reason": "no_change"}
            
            h = watcher.changes_hash(changes)
            last_alert = watcher.load_json(watcher.alert_state_path())
            last_hash = last_alert.get("hash")
            
            if h == last_hash:
                watcher.save_json(watcher.baseline_path(), new_snap)
                return {"action": "noop", "reason": "already_alerted", "changes": changes}
            
            msg = watcher.format_alert(changes)

            notified = False
            try:
                notified = bool(notifier(msg))
            except Exception:
                notified = False

            # Codex M4 #1: CHỈ ghi baseline + alert-hash khi gửi được. Notify fail
            # (tg down) → giữ baseline cũ để lần sau retry, KHÔNG mất cảnh báo.
            if notified:
                watcher.save_json(watcher.alert_state_path(), {"hash": h})
                watcher.save_json(watcher.baseline_path(), new_snap)

            return {
                "action": "alert",
                "message": msg,
                "changes": changes,
                "notified": notified,
            }
    except watcher.LockBusy:
        return {"action": "skipped", "reason": "locked"}

def main():
    parser = argparse.ArgumentParser(description="M4 PolyKit Watcher — Alert changes weekly")
    parser.add_argument("--dry-run", action="store_true", help="Chạy thử không gửi alert qua notifier thực tế")
    args = parser.parse_args()
    
    if args.dry_run:
        def dry_notifier(msg):
            print(f"[DRY RUN] {msg}", file=sys.stderr)
            return True
        result = run_watch(notifier=dry_notifier)
    else:
        result = run_watch()
        
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
