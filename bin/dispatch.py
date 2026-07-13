#!/usr/bin/env python3
import sys
import argparse
import json
from pathlib import Path

# Add the directory containing this script to sys.path to resolve 'lib'
sys.path.insert(0, str(Path(__file__).parent))

from lib.dispatcher import run_vendor

def main():
    parser = argparse.ArgumentParser(description="Multi-vendor CLI dispatch wrapper")
    parser.add_argument("vendor", choices=["gemini", "codex", "claude", "grok"], help="Vendor to dispatch to")
    parser.add_argument("model", nargs="?", default="auto", help="Model slug to use (default: auto)")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds (default: 120)")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format (default: text)")
    parser.add_argument("--cd", dest="workdir", default=None, help="Working directory (codex/grok)")
    parser.add_argument("--sandbox", choices=["read-only", "workspace-write"], default="read-only", help="Sandbox mode (default: read-only)")
    parser.add_argument("--result-json", action="store_true", help="Output the full DispatchResult as JSON instead of raw stdout")

    args = parser.parse_args()

    # Read prompt from stdin
    prompt = sys.stdin.read()

    # Dispatch task
    result = run_vendor(
        vendor=args.vendor,
        prompt=prompt,
        model=args.model,
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
        ))
    except Exception:
        pass

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
                sys.stderr.write("Warnings:\n")
                for warning in result.warnings:
                    sys.stderr.write(f"  - {warning}\n")

    sys.exit(0 if result.status == "ok" else 1)

if __name__ == "__main__":
    main()
