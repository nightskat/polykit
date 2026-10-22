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

def run_watch(
    state=None,
    now=None,
    notifier=None,
    detector=None,
    check_zdr: bool | None = None,
    renewal_verified: bool = False,
) -> dict:
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
            watcher.apply_last_known_good(new_snap, old_snap)
            changes = watcher.diff_snapshots(old_snap, new_snap)

            # Đánh giá DeepSeek ZDR: chỉ khi DeepSeek thực sự nằm trong lane
            # (vendor dsh/opencode/hermes) hoặc catalog có model deepseek*.
            should_check_zdr = check_zdr
            if should_check_zdr is None:
                zdr_vendors = {"dsh", "opencode", "hermes"}
                vendors_in_snap = set(new_snap.keys())
                deepseek_in_catalog = any(
                    "deepseek" in str(m).lower()
                    for v in new_snap.values() if isinstance(v, dict)
                    for m in (v.get("models") or [])
                )
                should_check_zdr = bool(vendors_in_snap & zdr_vendors) or deepseek_in_catalog

            zdr_info = None
            zdr_alert_due = False
            last_alert = watcher.load_json(watcher.alert_state_path())

            if should_check_zdr:
                zdr_info = watcher.check_deepseek_zdr(now=now, renewal_verified=renewal_verified)
                zdr_alert_due = watcher.check_zdr_alert_needed(zdr_info, last_alert)

            vendor_hash = watcher.changes_hash(changes) if changes else ""
            last_vendor_hash = last_alert.get("hash")
            vendor_alert_due = bool(changes) and (vendor_hash != last_vendor_hash)

            # Không có cảnh báo vendor mới VÀ không có ZDR alert due
            if not vendor_alert_due and not zdr_alert_due:
                watcher.save_json(watcher.baseline_path(), new_snap)
                if changes:
                    reason = "already_alerted"
                elif zdr_info and zdr_info.get("should_alert"):
                    reason = "already_alerted"
                else:
                    reason = "no_change"
                res = {"action": "noop", "reason": reason}
                if changes:
                    res["changes"] = changes
                if zdr_info:
                    res["zdr"] = zdr_info
                return res

            # Có ít nhất một alert cần gửi
            active_changes = changes if vendor_alert_due else []
            active_zdr = zdr_info if zdr_alert_due else None
            msg = watcher.format_alert(active_changes, zdr_info=active_zdr)

            notified = False
            try:
                notified = bool(notifier(msg))
            except Exception:
                notified = False

            # Codex M4 #1: CHỈ ghi baseline + alert-state khi gửi được.
            # Notify fail (tg down) → giữ state cũ để lần sau retry, KHÔNG mất cảnh báo.
            if notified:
                new_alert_state = dict(last_alert)
                if vendor_alert_due:
                    new_alert_state["hash"] = vendor_hash
                if zdr_alert_due and zdr_info:
                    new_alert_state["zdr_state"] = zdr_info["state"]
                watcher.save_json(watcher.alert_state_path(), new_alert_state)
                watcher.save_json(watcher.baseline_path(), new_snap)

            res = {
                "action": "alert",
                "message": msg,
                "changes": changes,
                "notified": notified,
            }
            if zdr_info:
                res["zdr"] = zdr_info
            return res

    except watcher.LockBusy:
        return {"action": "skipped", "reason": "locked"}

def main():
    parser = argparse.ArgumentParser(description="M4 PolyKit Watcher — Alert changes weekly")
    parser.add_argument("--dry-run", action="store_true", help="Chạy thử không gửi alert qua notifier thực tế")
    parser.add_argument("--snapshot", metavar="PATH",
                        help="Ghi bảng catalog máy-sinh ra PATH (chống trôi docs)")
    parser.add_argument("--now", metavar="DATE", help="Thời điểm chạy mô phỏng (YYYY-MM-DD hoặc ISO)")
    parser.add_argument("--check-zdr", action="store_true", help="Kiểm tra hạn DeepSeek ZDR")
    parser.add_argument("--renewal-verified", action="store_true", help="Đã xác minh gia hạn ZDR")
    args = parser.parse_args()

    watch_kwargs = {}
    if args.now:
        watch_kwargs["now"] = args.now
    if args.check_zdr:
        watch_kwargs["check_zdr"] = True
    if args.renewal_verified:
        watch_kwargs["renewal_verified"] = True

    if args.dry_run:
        def dry_notifier(msg):
            print(f"[DRY RUN] {msg}", file=sys.stderr)
            # Trả False — CHƯA gửi thật. Trả True thì run_watch tưởng đã báo xong,
            # ghi đè baseline + alert-hash, và lần chạy launchd thật sau đó im lặng:
            # dry-run NUỐT MẤT cảnh báo. Cùng luật thành thật như failover --dry-run.
            return False
        result = run_watch(notifier=dry_notifier, **watch_kwargs)
        result["dry_run"] = True
    else:
        result = run_watch(**watch_kwargs)

    if args.snapshot:
        # Snapshot đọc state.json vừa được doctor/run_watch làm mới. Ghi lỗi
        # KHÔNG được làm hỏng watcher — alert quan trọng hơn file docs.
        try:
            from lib.state_store import read_state
            from datetime import datetime, timezone
            st = read_state()
            if st:
                path = Path(args.snapshot)
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
