#!/usr/bin/env python3
from __future__ import annotations
import sys
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

# Add the directory containing this script to sys.path to resolve 'lib'
sys.path.insert(0, str(Path(__file__).parent))

from lib.dispatcher import run_vendor
from lib.vendor_config import (
    load_vendor_config,
    vendor_names,
    default_model,
    vendor_traps,
    vendor_verify_cmd,
    vendor_zero_quota_cmds,
    vendor_auth_hint,
)


def _run_doctor(vendor_name: str) -> int:
    """--doctor <vendor>: chạy verify_cmd, in trạng thái + model đang chạy.
    Ưu tiên zero_quota_cmds trước."""
    cfg = load_vendor_config()
    vcmd = vendor_verify_cmd(vendor_name, cfg)
    zq = vendor_zero_quota_cmds(vendor_name, cfg)
    hint = vendor_auth_hint(vendor_name, cfg)

    if not vcmd and not zq:
        sys.stderr.write(f"[polykit] vendor '{vendor_name}' không có verify_cmd/zero_quota_cmds\n")
        return 1

    executed_cmds = set()

    # Chạy verify_cmd
    if vcmd:
        executed_cmds.add(vcmd)
        sys.stderr.write(f"[polykit] doctor: running `{vcmd}` ...\n")
        try:
            res = subprocess.run(
                vcmd, shell=True,
                capture_output=True, text=True, timeout=30,
            )
            sys.stdout.write(res.stdout)
            if res.stderr:
                sys.stderr.write(res.stderr)
            if res.returncode != 0:
                sys.stderr.write(f"[polykit] verify_cmd exited {res.returncode}\n")
                if hint:
                    sys.stderr.write(f"[polykit] auth hint: {hint}\n")
                return res.returncode
        except subprocess.TimeoutExpired:
            sys.stderr.write(f"[polykit] verify_cmd timed out (30s)\n")
            return 124
        except Exception as e:
            sys.stderr.write(f"[polykit] verify_cmd error: {e}\n")
            return 1

    # Chạy zero_quota_cmds nếu có
    for zqc in zq[:2]:  # chạy tối đa 2 lệnh
        if zqc in executed_cmds:
            continue
        executed_cmds.add(zqc)
        sys.stderr.write(f"[polykit] doctor: running zero-quota `{zqc}` ...\n")
        try:
            res = subprocess.run(
                zqc, shell=True,
                capture_output=True, text=True, timeout=15,
            )
            sys.stdout.write(res.stdout)
            if res.stderr:
                sys.stderr.write(res.stderr)
            if res.returncode != 0:
                sys.stderr.write(f"[polykit] zero-quota cmd exited {res.returncode}\n")
                return res.returncode
        except subprocess.TimeoutExpired:
            sys.stderr.write(f"[polykit] zero-quota cmd timed out (15s)\n")
            return 124
        except Exception as e:
            sys.stderr.write(f"[polykit] zero-quota cmd error: {e}\n")
            return 1

    sys.stderr.write(f"[polykit] doctor: {vendor_name} OK\n")
    return 0


def main():
    cfg = load_vendor_config()
    names = vendor_names(cfg)

    parser = argparse.ArgumentParser(description="Multi-vendor CLI dispatch wrapper")
    parser.add_argument("vendor", choices=names, help="Vendor to dispatch to")
    parser.add_argument("model", nargs="?", default="auto", help="Model slug to use (default: auto)")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds (default: 120)")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format (default: text)")
    parser.add_argument("--cd", dest="workdir", default=None, help="Working directory (codex/grok)")
    parser.add_argument("--sandbox", choices=["read-only", "workspace-write"], default="read-only", help="Sandbox mode (default: read-only)")
    parser.add_argument("--result-json", action="store_true", help="Output the full DispatchResult as JSON instead of raw stdout")
    parser.add_argument("--doctor", action="store_true", help="Run verify_cmd for the vendor, print status")
    parser.add_argument("--no-traps", action="store_true", help="Suppress trap warnings on stderr")
    parser.add_argument("--dump-config", action="store_true", help="Print resolved model+vendor config and exit (0 token)")
    parser.add_argument("--allow-unknown-model", action="store_true", help="Allow models not listed in JSON")

    # Fix: Add REGISTRY vendors not in JSON (like openrouter)
    from lib.vendors import REGISTRY
    for k in REGISTRY:
        if k not in names:
            names.append(k)

    args = parser.parse_args()

    # --doctor mode
    if args.doctor:
        sys.exit(_run_doctor(args.vendor))

    # Resolve model auto → default_model từ vendors.json
    # 🔴 dsh đặc biệt: JSON ghi default=flash nhưng flash trả rỗng trên task nhiều bước.
    # Override cứng auto → pro ở CLI, khớp với DSH_DEFAULT_MODEL trong dispatcher.
    resolved_model = args.model
    if args.model == "auto":
        if args.vendor == "dsh":
            from lib.dispatch_core import DSH_DEFAULT_MODEL
            resolved_model = DSH_DEFAULT_MODEL
        else:
            dm = default_model(args.vendor, cfg)
            if dm:
                resolved_model = dm

    # Validate model
    if resolved_model != "auto":
        vendor_data = cfg.get("vendors", {}).get(args.vendor, {})
        valid_models = vendor_data.get("models")
        if valid_models is None:
            if not args.allow_unknown_model:
                sys.stderr.write(f"[polykit] warning: model list for vendor '{args.vendor}' is unknown, cannot validate '{resolved_model}'\n")
        elif isinstance(valid_models, list):
            if resolved_model not in valid_models:
                if not args.allow_unknown_model:
                    sys.stderr.write(f"[polykit] error: model '{resolved_model}' not in vendor '{args.vendor}' valid models.\n")
                    sys.stderr.write(f"Valid models: {', '.join(valid_models)}\n")
                    sys.stderr.write(f"Use --allow-unknown-model to bypass.\n")
                    sys.exit(2)

    # --dump-config: in cấu hình đã resolve, thoát 0 token
    if args.dump_config:
        info = {
            "vendor": args.vendor,
            "requested_model": args.model,
            "resolved_model": resolved_model,
            "default_model": default_model(args.vendor, cfg),
            "traps_count": len(vendor_traps(args.vendor, cfg)),
        }
        print(json.dumps(info, indent=2))
        sys.exit(0)

    # In traps ra stderr (trước khi dispatch)
    if not args.no_traps:
        traps = vendor_traps(args.vendor, cfg)
        if traps:
            sys.stderr.write(f"[polykit] ⚠ traps for {args.vendor}:\n")
            for i, trap in enumerate(traps, 1):
                sys.stderr.write(f"  {i}. {trap}\n")

    # Read prompt from stdin
    prompt = sys.stdin.read()

    # Dispatch task
    result = run_vendor(
        vendor=args.vendor,
        prompt=prompt,
        model=resolved_model,
        timeout=args.timeout,
        fmt=args.format,
        workdir=args.workdir,
        sandbox=args.sandbox
    )

    # M2 evidence log — best-effort, chỉ ở CLI boundary (không ghi khi test gọi lib).
    try:
        from lib.evidence import append_evidence, make_record
        from datetime import datetime, timezone
        append_evidence(make_record(
            result.vendor, result.model, result.status,
            datetime.now(timezone.utc).isoformat(), reason=result.reason,
            served_model=result.served_model,
        ))
    except Exception:
        pass

    # Model thật khác model đã gọi (router OR, lane agy, gemini auto) → báo ở stderr.
    # KHÔNG in ra stdout: stdout phải sạch để pipe sang lệnh khác.
    if result.served_model and result.served_model != resolved_model:
        sys.stderr.write(f"[polykit] served: {result.served_model}\n")

    if args.result_json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        if result.status == "ok":
            sys.stdout.write(result.stdout)
            # Ensure trailing newline if not present
            if result.stdout and not result.stdout.endswith('\n'):
                sys.stdout.write('\n')
        else:
            # Print failure details to stderr
            sys.stderr.write(f"ERROR: {result.summary}\n")
            if result.warnings:
                filtered_warnings = [w for w in result.warnings if "không nhận cờ model" not in w]
                if filtered_warnings:
                    sys.stderr.write("Warnings:\n")
                    for warning in filtered_warnings:
                        sys.stderr.write(f"  - {warning}\n")

    sys.exit(0 if result.status == "ok" else 1)

if __name__ == "__main__":
    main()
