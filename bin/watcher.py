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
            watcher.enrich_openrouter_models(new_snap)

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
    parser.add_argument("--snapshot", metavar="PATH",
                        help="Ghi bảng catalog máy-sinh ra PATH (chống trôi docs)")
    args = parser.parse_args()
    
    if args.dry_run:
        def dry_notifier(msg):
            print(f"[DRY RUN] {msg}", file=sys.stderr)
            # Trả False — CHƯA gửi thật. Trả True thì run_watch tưởng đã báo xong,
            # ghi đè baseline + alert-hash, và lần chạy launchd thật sau đó im lặng:
            # dry-run NUỐT MẤT cảnh báo. Cùng luật thành thật như failover --dry-run.
            return False
        result = run_watch(notifier=dry_notifier)
        result["dry_run"] = True
    else:
        result = run_watch()
        
    if args.snapshot:
        # Snapshot đọc state.json vừa được doctor/run_watch làm mới. Ghi lỗi
        # KHÔNG được làm hỏng watcher — alert quan trọng hơn file docs.
        try:
            from lib.state_store import read_state
            from datetime import datetime, timezone
            st = read_state()
            if st:
                path = Path(args.snapshot)
                # Codex review: --snapshot nhận path bất kỳ → gõ nhầm là ghi đè
                # source file. Chỉ cho ghi khi file CHƯA có, hoặc đã mang dấu
                # máy-sinh ở dòng đầu. Ghi atomic qua .tmp rồi replace.
                marker = "MÁY SINH"
                if path.exists():
                    head = path.read_text(encoding="utf-8", errors="replace")[:200]
                    if marker not in head:
                        raise RuntimeError(
                            f"{path} không phải file máy-sinh (thiếu dấu '{marker}') — từ chối ghi đè")
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text(
                    watcher.render_snapshot(st, datetime.now(timezone.utc).isoformat()),
                    encoding="utf-8")
                tmp.replace(path)
                result["snapshot"] = str(path)
            else:
                result["snapshot_error"] = "state.json chưa có — chạy doctor trước"
        except Exception as e:
            result["snapshot_error"] = f"{type(e).__name__}: {e}"

    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
