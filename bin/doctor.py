#!/usr/bin/env python3
from __future__ import annotations
import sys
import argparse
import json
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any

# Add bin/lib parent to sys.path so we can import lib
sys.path.insert(0, str(Path(__file__).parent))

from lib.vendors import detect_all, REGISTRY
from lib.state_store import build_state, write_state
from lib.states import VendorState, VendorProbe
from lib.evidence import read_evidence
from lib.doctor_quota import quota_capped_since

# Số bản ghi evidence đọc ngược lại khi suy trạng thái quota (xem run_doctor).
EVIDENCE_LOOKBACK = 500

# Mốc thời hạn Zero Data Retention (ZDR) đã xác minh thực tế (Plan mục 74, 139)
VERIFIED_ZDR_EXPIRY = "2026-10-31"
VERIFIED_ZDR_DATE = datetime.strptime(VERIFIED_ZDR_EXPIRY, "%Y-%m-%d").date()

def _failclosed_zdr_result(raw_expiry: Any) -> dict[str, Any]:
    return {
        "status": "unverified",
        "expiry": None,
        "days_left": 0,
        "renewal_verified": False,
        "warning": (
            f"DeepSeek ZDR expiry không hợp lệ hoặc thiếu ({raw_expiry!r}) — "
            "unverified failclosed (không có căn cứ gia hạn)"
        ),
    }

def check_zdr_expiry(zdr: Any, now: str | datetime | date | None = None) -> dict[str, Any]:
    """Kiểm tra thời hạn Zero Data Retention (ZDR) của vendor dựa theo mốc `now`.

    Cảnh báo:
    - Kẹp mốc min(config_expiry, verified_expiry 2026-10-31): không tin expiry config
      sau 2026-10-31; caller renewal/permanent không được tự ý gia hạn qua mốc verified.
    - Expiry sớm hơn (earlier expiry) được giữ nguyên.
    - Expiry invalid / missing (None, bool, dict, bad str): trả warning unverified
      failclosed, không crash doctor.
    - Trước ngày 2026-10-31: cảnh báo sắp hết hạn (còn N ngày).
    - Đúng ngày 2026-10-31: cảnh báo hết hạn hôm nay.
    - Sau ngày 2026-10-31: cảnh báo đã hết hạn (quá hạn N ngày).
    - Renewal chưa xác minh: phải cảnh báo (cần theo dõi gia hạn từng tháng).
    - Không dựa ngày hiện tại cố định.
    - Config expiry không được âm thầm gia hạn.
    """
    if now is None:
        now_date = datetime.now(timezone.utc).date()
    elif isinstance(now, datetime):
        now_date = now.date()
    elif isinstance(now, date):
        now_date = now
    elif isinstance(now, str):
        try:
            now_date = datetime.strptime(now[:10], "%Y-%m-%d").date()
        except Exception:
            now_date = datetime.now(timezone.utc).date()
    else:
        now_date = datetime.now(timezone.utc).date()

    if not isinstance(zdr, dict):
        return _failclosed_zdr_result(zdr)

    if "expiry" not in zdr:
        return _failclosed_zdr_result(None)

    raw_expiry = zdr.get("expiry")
    if raw_expiry is None or isinstance(raw_expiry, bool) or isinstance(raw_expiry, (dict, list, set, tuple)):
        return _failclosed_zdr_result(raw_expiry)

    if isinstance(raw_expiry, (datetime, date)):
        config_date = raw_expiry.date() if isinstance(raw_expiry, datetime) else raw_expiry
    elif isinstance(raw_expiry, str):
        clean_str = raw_expiry.strip()[:10]
        try:
            config_date = datetime.strptime(clean_str, "%Y-%m-%d").date()
        except Exception:
            return _failclosed_zdr_result(raw_expiry)
    else:
        return _failclosed_zdr_result(raw_expiry)

    is_tampered_future = config_date > VERIFIED_ZDR_DATE
    expiry_date = min(config_date, VERIFIED_ZDR_DATE)
    expiry_str = expiry_date.strftime("%Y-%m-%d")

    days_left = (expiry_date - now_date).days

    if days_left > 0:
        status = "expiring_soon"
        warn_text = f"DeepSeek ZDR sắp hết hạn vào {expiry_str} (còn {days_left} ngày)"
    elif days_left == 0:
        status = "expires_today"
        warn_text = f"DeepSeek ZDR hết hạn hôm nay ({expiry_str})"
    else:
        status = "expired"
        warn_text = f"DeepSeek ZDR đã hết hạn ({expiry_str}, quá hạn {abs(days_left)} ngày)"

    # Renewal / permanent caller không được tự gia hạn qua mốc verified.
    # Nếu config cố tình vượt mốc verified hoặc hiện tại đã quá hạn, renewal không được coi là hợp lệ.
    if is_tampered_future or days_left < 0:
        renewal_verified = False
    else:
        renewal_verified = bool(zdr.get("renewal_verified", False))

    if not renewal_verified:
        warn_text += " — gia hạn chưa được xác minh (cần theo dõi gia hạn từng tháng, không tự động gia hạn)"

    return {
        "status": status,
        "expiry": expiry_str,
        "days_left": days_left,
        "renewal_verified": renewal_verified,
        "warning": warn_text,
    }

def annotate_metadata(state: dict, probes: list[VendorProbe], now: str) -> dict:
    """Thêm thông tin probe_checked_at/source/catalog_source/stale/error và adapter meta
    (provider/quota_group cho opencode & hermes) như additive state metadata sau build_state.
    Không sửa states/store."""
    probe_map = {p.name: p for p in probes}
    for name, vdata in state.get("vendors", {}).items():
        spec = REGISTRY.get(name)
        p = probe_map.get(name)

        vdata["probe_checked_at"] = now
        vdata["source"] = "api" if spec and spec.binary is None else "cli"
        if spec and spec.models_cmd:
            vdata["catalog_source"] = "models_cmd"
        else:
            vdata["catalog_source"] = "none"
        vdata["stale"] = False
        if p and p.error:
            vdata["error"] = p.error

        # Hai adapter meta provider/quota_group opencode-go
        if spec and spec.provider:
            vdata["provider"] = spec.provider
        elif name in ("opencode", "hermes"):
            vdata["provider"] = "opencode-go"

        if spec and spec.quota_group:
            vdata["quota_group"] = spec.quota_group
        elif name in ("opencode", "hermes"):
            vdata["quota_group"] = "opencode-go"

    return state

def annotate_zdr(state: dict, now: str) -> dict:
    """Cảnh báo ZDR trước/ngày/sau expiry 2026-10-31 và cảnh báo renewal chưa xác minh.

    Metadata privacy nguồn Go chỉ áp dụng cho provider opencode-go (opencode, hermes);
    KHÔNG gán ZDR Go/no-train cho DSH DeepSeek official chỉ vì tên họ model
    (doctor fallback cũ cho dsh không có source evidence).
    Giữ warnings Go cho cả hermes và opencode.
    """
    for name, vdata in state.get("vendors", {}).items():
        # DSH DeepSeek official không có source evidence cho ZDR Go / no-train;
        # metadata privacy nguồn Go chỉ áp dụng cho provider opencode-go.
        provider = vdata.get("provider")
        if name == "dsh" or (provider != "opencode-go" and name not in ("opencode", "hermes")):
            continue

        zdr_info = None
        try:
            from lib.vendor_config import vendor_zdr
            zdr_info = vendor_zdr(name)
        except Exception:
            pass

        if zdr_info is None and (name in ("opencode", "hermes") or provider == "opencode-go"):
            zdr_info = {
                "supported": True,
                "expiry": "2026-10-31",
                "permanent": False,
                "renewal_verified": False,
                "note": "DeepSeek không train + ZDR hiện chỉ tới 31/10/2026, gia hạn từng tháng; không coi là vĩnh viễn"
            }

        if zdr_info and zdr_info.get("supported"):
            zdr_res = check_zdr_expiry(zdr_info, now=now)
            vdata["zdr_status"] = zdr_res["status"]
            vdata["zdr_warning"] = zdr_res["warning"]
            vdata["zdr"] = zdr_info
            v_warnings = vdata.setdefault("warnings", [])
            if zdr_res["warning"] not in v_warnings:
                v_warnings.append(zdr_res["warning"])
            state.setdefault("warnings", []).append(f"[{name}] {zdr_res['warning']}")

    return state

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
    annotate_metadata(state, probes, now)
    annotate_zdr(state, now)
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

        # Cảnh báo ZDR nếu có
        zdr_warn = vdata.get("zdr_warning")
        if zdr_warn:
            lines.append(f"  -> ⚠️ ZDR: {zdr_warn}")

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
