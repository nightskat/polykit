#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.notifier import default_notifier
from lib.quota import classify_signal, detect_cap


def _safe_notify(notifier, msg: str) -> bool:
    """Codex #2: alert fail (notifier raise/timeout) KHÔNG được làm sập failover."""
    try:
        return bool(notifier(msg))
    except Exception:
        return False


def handle_signal(
    stderr: str = "",
    pressure_pct: int | None = None,
    threshold: int = 80,
    vendor_hint: str | None = None,
    notifier=default_notifier,
    logger=None
) -> dict:
    signal = classify_signal(stderr, pressure_pct, threshold, vendor_hint)

    if signal == "cap":
        cap = detect_cap(stderr, vendor_hint)
        vendor_part = f" {cap.vendor}" if cap else ""
        tz_part = f" ({cap.timezone})" if cap and cap.timezone else ""
        reset_part = f" đến {cap.reset_hint}{tz_part}" if cap and cap.reset_hint else ""
        msg = f"⛔ Cap{vendor_part}{reset_part}. Lane: codex main / gemini worker."
        notified = _safe_notify(notifier, msg)
        return {
            "action": "ping_reactive",
            "signal": "cap",
            "message": msg,
            "notified": notified
        }
    elif signal == "pressure":
        msg = f"⚠️ Claude còn ~{100 - pressure_pct}% (pressure {pressure_pct}%). Handoff sang đâu? codex / gemini / để cap"
        notified = _safe_notify(notifier, msg)
        return {
            "action": "ping_proactive",
            "signal": "pressure",
            "message": msg,
            "notified": notified
        }
    elif signal == "unknown":
        if logger:
            logger(stderr)
        return {
            "action": "log_silent",
            "signal": "unknown",
            "notified": False
        }
    else:
        return {
            "action": "noop",
            "signal": "none",
            "notified": False
        }

def main():
    import argparse
    import json
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--stderr-file", type=str, help="Path to stderr log file")
    parser.add_argument("--pressure", type=int, help="Pressure percentage")
    parser.add_argument("--threshold", type=int, default=80, help="Pressure threshold")
    parser.add_argument("--vendor", type=str, help="Vendor hint")
    
    args = parser.parse_args()
    
    stderr = ""
    if args.stderr_file:
        try:
            with open(args.stderr_file, "r", encoding="utf-8") as f:
                stderr = f.read()
        except Exception:
            pass
            
    res = handle_signal(
        stderr=stderr,
        pressure_pct=args.pressure,
        threshold=args.threshold,
        vendor_hint=args.vendor
    )
    print(json.dumps(res))

if __name__ == "__main__":
    main()
