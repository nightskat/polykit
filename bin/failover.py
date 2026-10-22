#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any
import json

sys.path.insert(0, str(Path(__file__).parent))

from lib.notifier import default_notifier
from lib.quota import classify_signal, detect_cap, evaluate_quota_windows, CapInfo


def _safe_notify(notifier, msg: str) -> bool:
    """Codex #2: alert fail (notifier raise/timeout) KHÔNG được làm sập failover."""
    try:
        return bool(notifier(msg))
    except Exception:
        return False


def filter_failover_candidates(
    candidates: list[Any],
    vendor_hint: str | None = None,
    is_vision: bool = False,
    is_sensitive: bool = False,
) -> list[Any]:
    """Lọc danh sách ứng viên failover theo chính sách bảo mật và quota group:

    1. Cấm tuyệt đối model contributor (rủi ro data training).
    2. Cấm model free (free chỉ được chọn tường minh qua --model, cấm trong failover).
    3. Cấm ứng viên cùng quota_group với vendor_hint (vd: hermes và opencode cùng 'opencode-go').
    4. Không tự động dispatch task vision hoặc sensitive.
    """
    if not candidates:
        return []

    try:
        from lib.model_policy import (
            SelectionSource,
            check_model_policy,
            is_contributor_model,
            is_free_model,
            GO_VENDORS,
        )
    except Exception:
        from bin.lib.model_policy import (
            SelectionSource,
            check_model_policy,
            is_contributor_model,
            is_free_model,
            GO_VENDORS,
        )

    try:
        from lib.vendor_config import vendor_quota_group, default_model, vendor_names
    except Exception:
        from bin.lib.vendor_config import vendor_quota_group, default_model, vendor_names

    source_quota_group: str | None = None
    if vendor_hint:
        v_clean = vendor_hint.strip().lower()
        try:
            source_quota_group = vendor_quota_group(v_clean)
        except Exception:
            pass
        if not source_quota_group and v_clean in GO_VENDORS:
            source_quota_group = "opencode-go"

    filtered: list[Any] = []

    known_vendors = set()
    try:
        known_vendors = set(vendor_names())
    except Exception:
        known_vendors = {"agy", "dsh", "grok", "codex", "gemini", "claude", "openrouter", "opencode", "hermes"}

    for cand in candidates:
        cand_vendor: str | None = None
        cand_model: str | None = None

        if isinstance(cand, dict):
            cand_vendor = cand.get("vendor")
            cand_model = cand.get("model")
            if cand_vendor and is_contributor_model(cand_vendor):
                continue
            if cand_vendor and is_free_model(cand_vendor):
                continue
        elif isinstance(cand, str):
            c_str = cand.strip()
            # Chuỗi candidate mang đặc trưng contributor hoặc free -> loại ngay
            if is_contributor_model(c_str) or is_free_model(c_str):
                continue

            if c_str.lower() in known_vendors:
                cand_vendor = c_str.lower()
                try:
                    cand_model = default_model(cand_vendor)
                except Exception:
                    cand_model = None
            else:
                cand_model = c_str
                if "/" in c_str:
                    cand_vendor = c_str.split("/")[0].lower()

        # 1. Cùng quota_group với vendor nguồn -> loại trừ ("cap một harness không gợi ý harness kia")
        if source_quota_group and cand_vendor:
            cand_qg = None
            try:
                cand_qg = vendor_quota_group(cand_vendor)
            except Exception:
                pass
            if not cand_qg and cand_vendor in GO_VENDORS:
                cand_qg = "opencode-go"

            if cand_qg and cand_qg == source_quota_group:
                continue

        # 2. Kiểm tra model policy nguồn FAILOVER: cấm free và contributor
        if cand_model:
            if is_contributor_model(cand_model):
                continue
            if is_free_model(cand_model):
                continue
            try:
                decision = check_model_policy(
                    selector=cand_model,
                    vendor=cand_vendor,
                    source=SelectionSource.FAILOVER,
                )
                if decision.is_blocked:
                    continue
            except Exception:
                continue

        filtered.append(cand)

    return filtered


def handle_signal(
    stderr: str = "",
    pressure_pct: int | None = None,
    threshold: int = 80,
    vendor_hint: str | None = None,
    notifier=default_notifier,
    logger=None,
    windows: dict | list | None = None,
    candidates: list[Any] | None = None,
    is_vision: bool = False,
    is_sensitive: bool = False,
) -> dict:
    windows_eval = None
    if windows is not None:
        windows_eval = evaluate_quota_windows(windows)

    if windows_eval is not None and windows_eval.get("is_capped"):
        signal = "cap"
    elif windows_eval is not None and windows_eval.get("status") == "unknown" and not stderr.strip():
        signal = "unknown"
    else:
        signal = classify_signal(stderr, pressure_pct, threshold, vendor_hint)

    if signal == "cap":
        cap = detect_cap(stderr, vendor_hint)
        if cap is None and windows_eval and windows_eval.get("is_capped"):
            cap = CapInfo(
                vendor=vendor_hint or "unknown",
                reset_hint=windows_eval.get("reset_at"),
            )

        vendor_part = f" {cap.vendor}" if cap else ""
        tz_part = f" ({cap.timezone})" if cap and cap.timezone else ""
        reset_part = f" đến {cap.reset_hint}{tz_part}" if cap and cap.reset_hint else ""

        filtered_candidates = None
        if candidates is not None:
            filtered_candidates = filter_failover_candidates(
                candidates,
                vendor_hint=cap.vendor if cap else vendor_hint,
                is_vision=is_vision,
                is_sensitive=is_sensitive,
            )
            cand_names = [
                c.get("vendor", str(c)) if isinstance(c, dict) else str(c)
                for c in filtered_candidates
            ]
            rec_part = f" Gợi ý: {', '.join(cand_names)}." if cand_names else " Không có ứng viên phù hợp."
            safety_part = " (Khuyến nghị, không tự động dispatch/retry)."
            msg = f"⛔ Cap{vendor_part}{reset_part}.{rec_part}{safety_part}"
        else:
            msg = f"⛔ Cap{vendor_part}{reset_part}. Lane: codex main / gemini worker."

        notified = _safe_notify(notifier, msg)
        res = {
            "action": "ping_reactive",
            "signal": "cap",
            "message": msg,
            "notified": notified,
            "auto_dispatch": False,
            "auto_retry": False,
        }
        if filtered_candidates is not None:
            res["recommended_candidates"] = filtered_candidates
        if windows_eval is not None:
            res["windows_evaluation"] = windows_eval
        return res

    elif signal == "pressure":
        filtered_candidates = None
        if candidates is not None:
            filtered_candidates = filter_failover_candidates(
                candidates,
                vendor_hint=vendor_hint,
                is_vision=is_vision,
                is_sensitive=is_sensitive,
            )
            cand_names = [
                c.get("vendor", str(c)) if isinstance(c, dict) else str(c)
                for c in filtered_candidates
            ]
            handoff_target = f"{', '.join(cand_names)} / để cap" if cand_names else "để cap"
            msg = f"⚠️ {vendor_hint or 'Claude'} còn ~{100 - pressure_pct}% (pressure {pressure_pct}%). Handoff sang: {handoff_target}"
        else:
            msg = f"⚠️ Claude còn ~{100 - pressure_pct}% (pressure {pressure_pct}%). Handoff sang đâu? codex / gemini / để cap"

        notified = _safe_notify(notifier, msg)
        res = {
            "action": "ping_proactive",
            "signal": "pressure",
            "message": msg,
            "notified": notified,
            "auto_dispatch": False,
            "auto_retry": False,
        }
        if filtered_candidates is not None:
            res["recommended_candidates"] = filtered_candidates
        return res

    elif signal == "unknown":
        if logger:
            logger(stderr)
        res = {
            "action": "log_silent",
            "signal": "unknown",
            "notified": False,
            "auto_dispatch": False,
            "auto_retry": False,
        }
        if windows_eval is not None:
            res["windows_evaluation"] = windows_eval
        return res

    else:
        return {
            "action": "noop",
            "signal": "none",
            "notified": False,
            "auto_dispatch": False,
            "auto_retry": False,
        }

def main():
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--stderr-file", type=str, help="Path to stderr log file")
    parser.add_argument("--pressure", type=int, help="Pressure percentage")
    parser.add_argument("--threshold", type=int, default=80, help="Pressure threshold")
    parser.add_argument("--vendor", type=str, help="Vendor hint")
    parser.add_argument("--windows", type=str, help="JSON string or file path for quota windows")
    parser.add_argument("--candidates", type=str, help="Comma-separated or JSON list of candidate vendors")
    parser.add_argument("--vision", action="store_true", help="Vision modality task")
    parser.add_argument("--sensitive", action="store_true", help="Sensitive task")
    parser.add_argument("--dry-run", action="store_true",
                        help="Không gửi tg-ping thật — chỉ in message sẽ gửi")

    args = parser.parse_args()

    stderr = ""
    if args.stderr_file:
        try:
            with open(args.stderr_file, "r", encoding="utf-8") as f:
                stderr = f.read()
        except Exception:
            pass

    windows = None
    if args.windows:
        try:
            if Path(args.windows).is_file():
                with open(args.windows, "r", encoding="utf-8") as f:
                    windows = json.load(f)
            else:
                windows = json.loads(args.windows)
        except Exception:
            pass

    candidates = None
    if args.candidates:
        try:
            candidates = json.loads(args.candidates)
        except Exception:
            candidates = [c.strip() for c in args.candidates.split(",") if c.strip()]

    # --dry-run: notifier chỉ in ra stderr, KHÔNG gọi tg-ping (Tuan yêu cầu sau MVP test).
    dry_notifier = None
    if args.dry_run:
        def dry_notifier(msg, silent=False):
            print(f"[DRY RUN] {msg}", file=sys.stderr)
            # Codex MVP #4: trả False — thành thật CHƯA gửi, không đánh lừa automation.
            return False

    kwargs = {
        "stderr": stderr,
        "pressure_pct": args.pressure,
        "threshold": args.threshold,
        "vendor_hint": args.vendor,
        "windows": windows,
        "candidates": candidates,
        "is_vision": args.vision,
        "is_sensitive": args.sensitive,
    }
    if dry_notifier is not None:
        kwargs["notifier"] = dry_notifier
    res = handle_signal(**kwargs)
    if args.dry_run:
        res["dry_run"] = True  # đánh dấu rõ: notified=false vì dry-run, không phải gửi lỗi
    print(json.dumps(res))

if __name__ == "__main__":
    main()
