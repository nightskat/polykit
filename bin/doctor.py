#!/usr/bin/env python3
import sys
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

# Add bin/lib parent to sys.path so we can import lib
sys.path.insert(0, str(Path(__file__).parent))

from lib.vendors import detect_all, REGISTRY
from lib.state_store import build_state, write_state

def run_doctor(probes=None, now=None) -> dict:
    if probes is None:
        probes = detect_all()
    if now is None:
        now = datetime.now(timezone.utc).isoformat()
    state = build_state(probes, now)
    write_state(state)
    return state

def render_table(state: dict) -> str:
    vendors = ["codex", "gemini", "claude", "grok"]
    lines = []
    # Header
    lines.append(f"{'VENDOR':<10} | {'STATE':<20} | {'PATH':<50} | {'VERSION':<15}")
    lines.append("-" * 105)
    
    for name in vendors:
        vdata = state.get("vendors", {}).get(name, {})
        v_state = vdata.get("state", "not_installed")
        v_path = vdata.get("cli_path") or "None"
        v_ver = vdata.get("cli_version") or "None"
        
        lines.append(f"{name:<10} | {v_state:<20} | {v_path:<50} | {v_ver:<15}")
        # Hint đúng theo state: chưa cài → hướng dẫn cài; cài rồi chưa auth → hint auth.
        if v_state == "not_installed":
            lines.append(f"  -> Chưa cài — cài binary `{vdata.get('binary', name)}`")
        elif v_state == "installed_not_authed":
            hint = vdata.get("auth_hint")
            if hint:
                lines.append(f"  -> {hint}")
        elif v_state == "quota_capped":
            lines.append("  -> Hết quota — chuyển lane khác")
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Kiểm tra trạng thái vendor (state machine)")
    parser.add_argument("--json", action="store_true", help="In trạng thái dưới dạng JSON")
    args = parser.parse_args()
    
    state = run_doctor()
    if args.json:
        print(json.dumps(state, indent=2, ensure_ascii=False))
    else:
        print(render_table(state))

if __name__ == "__main__":
    main()
