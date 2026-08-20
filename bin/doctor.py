#!/usr/bin/env python3
from __future__ import annotations
import sys
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

# Add bin/lib parent to sys.path so we can import lib
sys.path.insert(0, str(Path(__file__).parent))

from lib.vendors import detect_all, REGISTRY
from lib.state_store import build_state, write_state
from lib.states import VendorState
from lib.evidence import read_evidence
from lib.doctor_quota import quota_capped_since

# Số bản ghi evidence đọc ngược lại khi suy trạng thái quota (xem run_doctor).
EVIDENCE_LOOKBACK = 500

def annotate_quota_capped(state: dict, records: list[dict], now: str) -> dict:
    """BUG-4: hạ vendor `ready` xuống `quota_capped` nếu log evidence vừa có
    bản ghi quota_capped còn hiệu lực (trong cửa sổ, chưa bị status=ok đè).

    KHÔNG hạ not_installed / installed_not_authed / auth_unverified — giữ nguyên
    thứ tự máy trạng thái trong states.py. Chỉ đụng vendor đang `ready`."""
    capped = quota_capped_since(records, now)
    for name, vdata in state.get("vendors", {}).items():
        if name in capped and vdata.get("state") == VendorState.READY.value:
            vdata["state"] = VendorState.QUOTA_CAPPED.value
            # Giữ mốc thời gian làm căn cứ để bảng doctor nói rõ TẠI SAO capped.
            vdata["quota_evidence_ts"] = capped[name]
    return state

def run_doctor(probes=None, now=None, records=None) -> dict:
    if probes is None:
        probes = detect_all()
    if now is None:
        now = datetime.now(timezone.utc).isoformat()
    if records is None:
        # limit mặc định (20) KHÔNG đủ: chỉ cần vài lượt dispatch sau lúc bị cap là
        # bản ghi quota_capped trôi ra khỏi cửa sổ đọc, doctor lại báo ready như cũ.
        # Đọc rộng hơn hẳn cửa sổ 5 giờ; lọc theo thời gian đã nằm ở quota_capped_since.
        records = read_evidence(limit=EVIDENCE_LOOKBACK)
    state = build_state(probes, now)
    annotate_quota_capped(state, records, now)
    write_state(state)
    return state

def render_table(state: dict) -> str:
    # Dynamic theo state (thứ tự REGISTRY) — vendor mới như openrouter tự hiện.
    vendors = list(state.get("vendors", {}).keys())
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
        elif v_state == "auth_unverified":
            lines.append("  -> Probe phụ không xác minh được auth; thử dispatch nhỏ khi cần")
        elif v_state == "quota_capped":
            ts = vdata.get("quota_evidence_ts")
            if ts:
                lines.append(f"  -> Hết quota — bằng chứng dispatch lúc {ts}")
            else:
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
