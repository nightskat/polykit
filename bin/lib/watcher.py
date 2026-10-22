from __future__ import annotations
import json
import hashlib
import os
import time
from datetime import datetime, date, timezone
from pathlib import Path
from lib.paths import user_state_dir

class LockBusy(Exception):
    pass

def lock_path() -> Path:
    return Path(user_state_dir("polykit")) / "watch.lock.d"

def baseline_path() -> Path:
    return Path(user_state_dir("polykit")) / "watch-baseline.json"

def alert_state_path() -> Path:
    return Path(user_state_dir("polykit")) / "watch-last-alert.json"

class WatchLock:
    def __init__(self, path=None, stale_sec=300):
        self.path = lock_path() if path is None else Path(path)
        self.stale_sec = stale_sec
        # Token định danh chủ lock (Codex M4 #4) — pid + thời điểm chiếm.
        self.token = f"{os.getpid()}-{time.time_ns()}"
        self._token_file = self.path / "owner"

    def _claim(self):
        self.path.mkdir(parents=True, exist_ok=False)
        self._token_file.write_text(self.token, encoding="utf-8")

    def __enter__(self):
        try:
            self._claim()
        except FileExistsError:
            try:
                age = time.time() - self.path.stat().st_mtime
            except Exception:
                age = 0
            if age > self.stale_sec:
                # Chủ cũ coi như chết: xoá token + dir rồi chiếm lại.
                try:
                    self._token_file.unlink()
                except Exception:
                    pass
                try:
                    self.path.rmdir()
                except Exception:
                    pass
                try:
                    self._claim()
                except Exception as e:
                    raise LockBusy("Lock busy (reclaim failed)") from e
            else:
                raise LockBusy("Lock is busy and not stale")
        return self

    def _owned_by_me(self) -> bool:
        try:
            return self._token_file.read_text(encoding="utf-8") == self.token
        except Exception:
            return False

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Chỉ nhả lock nếu token khớp — không xoá nhầm lock process khác đã chiếm.
        if not self._owned_by_me():
            return
        try:
            self._token_file.unlink()
        except Exception:
            pass
        try:
            self.path.rmdir()
        except Exception:
            pass

def snapshot_from_state(state: dict) -> dict:
    """Tạo snapshot catalog từ state của doctor / probe.
    Bổ sung metadata additive: provenance / catalog_source, timestamp / catalog_timestamp,
    stale, error mà không phá vỡ schema snapshot cũ."""
    vendors_data = state.get("vendors", {}) if isinstance(state, dict) else {}
    snap = {}
    gen_at = state.get("generated_at") if isinstance(state, dict) else None
    for vendor, vdata in vendors_data.items():
        if not isinstance(vdata, dict):
            continue
        models = sorted(list(vdata.get("models") or []))

        # Additive metadata
        source = (
            vdata.get("catalog_source")
            or vdata.get("provenance")
            or vdata.get("source")
            or ("api" if vendor == "openrouter" else "cli")
        )
        ts = (
            vdata.get("catalog_timestamp")
            or vdata.get("timestamp")
            or vdata.get("probe_checked_at")
            or gen_at
        )
        is_stale = bool(vdata.get("stale", False))

        snap[vendor] = {
            "models": models,
            "version": vdata.get("cli_version"),
            "state": vdata.get("state"),
            "error": vdata.get("error"),
            "catalog_source": source,
            "provenance": source,
            "catalog_timestamp": ts,
            "timestamp": ts,
            "stale": is_stale,
        }
    return snap

def apply_last_known_good(new_snap: dict, old_snap: dict) -> dict:
    """Giữ last-known-good catalog cho vendor gặp lỗi fetch/timeout/offline
    để diff_snapshots không báo removed giả ('-X models').
    Có error nhưng catalog cũ giữ nguồn/ngày cũ và đánh dấu stale."""
    if not old_snap or not isinstance(old_snap, dict):
        return new_snap

    for vendor, vdata in new_snap.items():
        old_v = old_snap.get(vendor)
        if not old_v or not isinstance(old_v, dict):
            continue

        has_error = bool(vdata.get("error"))
        models_dropped = not vdata.get("models") and bool(old_v.get("models"))
        # Catalog không đọc được vì lý do KHÔNG phải lỗi probe (auth chưa xác minh)
        # → giữ last-known-good. `not_installed` KHÔNG thuộc nhóm này: gỡ vendor
        # thật thì phải báo removed, không được mark stale rồi mù vĩnh viễn.
        catalog_unreadable = vdata.get("state") in ("auth_unverified", "installed_not_authed")

        if has_error or (models_dropped and catalog_unreadable):
            old_models = old_v.get("models")
            if old_models:
                # Giữ last-known-good models
                vdata["models"] = sorted(list(old_models))
                vdata["stale"] = True

                # Giữ nguyên nguồn và ngày cũ
                old_source = old_v.get("catalog_source") or old_v.get("provenance")
                if old_source:
                    vdata["catalog_source"] = old_source
                    vdata["provenance"] = old_source

                old_ts = old_v.get("catalog_timestamp") or old_v.get("timestamp")
                if old_ts:
                    vdata["catalog_timestamp"] = old_ts
                    vdata["timestamp"] = old_ts
    return new_snap

def diff_snapshots(old: dict, new: dict) -> list[dict]:
    if not old:
        return []
    
    changes = []
    all_vendors = sorted(list(set(old.keys()) | set(new.keys())))
    for v in all_vendors:
        if v not in old:
            changes.append({"vendor": v, "type": "appeared"})
        elif v not in new:
            changes.append({"vendor": v, "type": "disappeared"})
        else:
            v_old = old[v]
            v_new = new[v]
            
            if v_old.get("version") != v_new.get("version"):
                changes.append({
                    "vendor": v,
                    "type": "version",
                    "old": v_old.get("version"),
                    "new": v_new.get("version")
                })
            
            if v_old.get("state") != v_new.get("state"):
                changes.append({
                    "vendor": v,
                    "type": "state",
                    "old": v_old.get("state"),
                    "new": v_new.get("state")
                })
            
            old_models = set(v_old.get("models") or [])
            new_models = set(v_new.get("models") or [])
            if old_models != new_models:
                added = sorted(list(new_models - old_models))
                removed = sorted(list(old_models - new_models))
                changes.append({
                    "vendor": v,
                    "type": "models",
                    "added": added,
                    "removed": removed
                })
    return changes

def sorted_change_key(c: dict) -> tuple:
    vendor = c.get("vendor", "")
    ctype = c.get("type", "")
    return (vendor, ctype)

def changes_hash(changes: list[dict]) -> str:
    sorted_changes = sorted(changes, key=sorted_change_key)
    return hashlib.sha256(json.dumps(sorted_changes, sort_keys=True).encode()).hexdigest()

def is_offline(snapshot: dict) -> bool:
    # Codex M4 #2: offline = detect fail hạ tầng (mọi vendor có error field),
    # KHÔNG phải not_installed. Gỡ vendor thật (not_installed, error=None) vẫn
    # được báo 'disappeared' — không bị mark offline rồi mù vĩnh viễn.
    if not snapshot:
        return True
    return all(bool(v.get("error")) for v in snapshot.values())

OR_MODELS_API = "https://openrouter.ai/api/v1/models"

def fetch_or_free_models(timeout: int = 15) -> list[str] | None:
    """Lấy danh sách model free trên OpenRouter (pricing.prompt == '0').
    Trả None khi lỗi mạng/format — caller quyết định fallback, KHÔNG trả []
    để phân biệt 'không fetch được' với 'OR thật sự hết model free'."""
    import urllib.request
    try:
        req = urllib.request.Request(OR_MODELS_API, headers={"User-Agent": "polykit-watcher"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
        return sorted(m["id"] for m in data.get("data", [])
                      if isinstance(m, dict) and m.get("pricing", {}).get("prompt") == "0")
    except Exception:
        return None

def enrich_openrouter_models(snap: dict, fetcher=fetch_or_free_models) -> None:
    """Ghép OR free models vào snapshot để diff_snapshots bắt thêm/bớt model.
    Probe API-key (vendors.py) luôn trả models=[] vì OR không có CLI — watcher
    tự fetch ở đây, NGOÀI critical path dispatch. Fetch fail → giữ models từ
    baseline cũ để không alert giả 'removed toàn bộ', đồng thời giữ timestamp
    cũ và đánh dấu stale."""
    if "openrouter" not in snap:
        return
    ids = fetcher()
    if ids is None:
        old = load_json(baseline_path())
        old_or = (old.get("openrouter") or {}) if isinstance(old, dict) else {}
        ids = old_or.get("models") or []
        snap["openrouter"]["stale"] = True
        if old_or.get("catalog_source"):
            snap["openrouter"]["catalog_source"] = old_or["catalog_source"]
            snap["openrouter"]["provenance"] = old_or["catalog_source"]
        if old_or.get("catalog_timestamp"):
            snap["openrouter"]["catalog_timestamp"] = old_or["catalog_timestamp"]
            snap["openrouter"]["timestamp"] = old_or["catalog_timestamp"]
        if not snap["openrouter"].get("error"):
            snap["openrouter"]["error"] = "fetch_error"
    else:
        snap["openrouter"]["stale"] = False
        snap["openrouter"]["catalog_source"] = "api"
        snap["openrouter"]["provenance"] = "api"
    snap["openrouter"]["models"] = sorted(ids)

# --- Codex JSON Catalog Parser ---

def _fallback_parse_codex_json(raw: str) -> list[str]:
    """Fallback an toàn để parse JSON catalog của Codex khi vendors.parse_codex_models chưa có.
    Hỗ trợ cả JSON object {models: [...]}, {data: [...]}, list JSON, và JSONL.
    Không invent module import hard fail."""
    if not raw or not raw.strip():
        return []
    text = raw.strip()

    data = None
    try:
        data = json.loads(text)
    except Exception:
        # Thử JSON Lines
        lines_data = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                lines_data.append(json.loads(line))
            except Exception:
                pass
        if lines_data:
            data = lines_data

    if data is None:
        return []

    out: list[str] = []

    def _extract_slug(item) -> str | None:
        if isinstance(item, str):
            val = item.strip()
            return val if val else None
        if isinstance(item, dict):
            for k in ("id", "slug", "model", "name"):
                v = item.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        return None

    if isinstance(data, list):
        for item in data:
            s = _extract_slug(item)
            if s and s not in out:
                out.append(s)
    elif isinstance(data, dict):
        candidates = data.get("models") or data.get("data") or data.get("items")
        if isinstance(candidates, list):
            for item in candidates:
                s = _extract_slug(item)
                if s and s not in out:
                    out.append(s)
        elif isinstance(candidates, dict):
            for k, v in candidates.items():
                s = _extract_slug(v) or k
                if s and s not in out:
                    out.append(s)
        else:
            for k, v in data.items():
                if isinstance(v, dict) and any(c in k for c in "-._/"):
                    if k not in out:
                        out.append(k)

    return out

def _load_vendors_module():
    """Import lib.vendors theo cách chạy thật (bin/ trên sys.path) hoặc từ repo root.
    Không import module lạ; thiếu module thì trả None để caller dùng fallback."""
    try:
        import lib.vendors as vendors
        return vendors
    except Exception:
        pass
    try:
        import bin.lib.vendors as vendors
        return vendors
    except Exception:
        return None


def parse_codex_models(raw_output: str) -> list[str]:
    """Parse Codex catalog output (JSON).

    Ưu tiên `vendors.parse_codex_models` do lot doctor thêm; thiếu function thì
    dùng parser JSON nội bộ — KHÔNG invent module import hard-fail.
    Parser chuẩn lỗi thì trả [] (coi như catalog không đọc được), không lấy
    parser khác bịa ra slug mà parser chuẩn đã từ chối.
    """
    vendors = _load_vendors_module()
    fn = getattr(vendors, "parse_codex_models", None) if vendors is not None else None
    if callable(fn):
        try:
            parsed = fn(raw_output)
        except Exception:
            return []
        if not isinstance(parsed, (list, tuple)):
            return []
        return [m for m in parsed if isinstance(m, str)]

    return _fallback_parse_codex_json(raw_output)

parse_codex_catalog = parse_codex_models

# --- Model Policy & Route Recommendations ---

def _safe_is_contributor(name: str) -> bool:
    try:
        from lib.model_policy import is_contributor_model
        return is_contributor_model(name)
    except Exception:
        try:
            from bin.lib.model_policy import is_contributor_model
            return is_contributor_model(name)
        except Exception:
            return bool(name and "contributor" in str(name).lower())

def _safe_is_free(name: str) -> bool:
    try:
        from lib.model_policy import is_free_model
        return is_free_model(name)
    except Exception:
        try:
            from bin.lib.model_policy import is_free_model
            return is_free_model(name)
        except Exception:
            lower = str(name).lower() if name else ""
            return bool("free" in lower or lower.endswith(":free"))

def is_route_candidate(model_name: str) -> bool:
    """Kiểm tra model có đủ điều kiện làm route recommendation không.
    Lọc bỏ:
    - contributor (chặn cứng data training)
    - free (chỉ cho phép khi chọn tường minh, cấm auto / default / failover route)"""
    if not model_name:
        return False
    if _safe_is_contributor(model_name):
        return False
    if _safe_is_free(model_name):
        return False
    return True

def filter_route_recommendations(models: list[str]) -> list[str]:
    """Lọc danh sách model chỉ giữ lại các model hợp lệ cho route recommendations."""
    return [m for m in (models or []) if is_route_candidate(m)]

def get_route_recommendations(snapshot: dict, vendor: str | None = None) -> list[str] | dict[str, list[str]]:
    """Gợi ý route recommendations từ catalog snapshot:
    Lọc sạch contributor/free khỏi recommendations.
    Nếu chỉ định vendor: trả về list[str].
    Nếu không chỉ định: trả về dict[str, list[str]]."""
    if vendor is not None:
        vdata = snapshot.get(vendor) or {}
        raw_models = vdata.get("models") or []
        return filter_route_recommendations(raw_models)

    routes = {}
    for vname, vdata in snapshot.items():
        if isinstance(vdata, dict):
            raw_models = vdata.get("models") or []
            routes[vname] = filter_route_recommendations(raw_models)
    return routes

def get_model_advisory(model_name: str) -> str | None:
    """Gắn nhãn advisory cho model trong catalog:
    Catalog thông tin giữ model banned được nếu rõ advisory, đừng coi catalog là permission."""
    if _safe_is_contributor(model_name):
        return "banned: contributor model trains on user data (no routing)"
    if _safe_is_free(model_name):
        return "advisory: free model requires explicit selection (no auto route)"
    return None

def get_catalog_with_advisories(models: list[str]) -> list[dict]:
    """Trả về catalog cùng trạng thái advisory và quyền routing."""
    res = []
    for m in models:
        adv = get_model_advisory(m)
        res.append({
            "model": m,
            "banned": "banned" in (adv or ""),
            "advisory": adv,
            "allowed_for_routing": is_route_candidate(m),
        })
    return res

# --- DeepSeek ZDR Expiry & Renewal ---

DEEPSEEK_ZDR_EXPIRY = "2026-10-31"

def parse_date_value(val: str | datetime | date | None) -> date:
    if val is None:
        return datetime.now(timezone.utc).date()
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        val_clean = val.strip().split("T")[0]
        return date.fromisoformat(val_clean)
    raise ValueError(f"Cannot parse date from {val!r}")

def check_deepseek_zdr(
    now: str | datetime | date | None = None,
    expiry: str | date = DEEPSEEK_ZDR_EXPIRY,
    renewal_verified: bool = False,
    soon_days: int = 7,
) -> dict:
    """Đánh giá trạng thái ZDR của DeepSeek (Plan mục 74, Plan mục 139):
    - expiry mặc định: 2026-10-31
    - Các state:
      * 'expired': khi now > expiry
      * 'on': khi now == expiry (đúng ngày hết hạn)
      * 'soon': khi 0 <= (expiry - now).days <= soon_days (sắp hết hạn)
      * 'renewal_unverified': khi còn hạn (> soon_days) nhưng renewal_verified=False
      * 'ok': khi còn hạn và renewal_verified=True
    - Cảnh báo rõ ràng tình trạng renewal (chưa xác minh gia hạn).
    """
    today = parse_date_value(now)
    exp_date = parse_date_value(expiry)
    days_left = (exp_date - today).days

    if days_left < 0:
        state = "expired"
        msg = f"DeepSeek ZDR ĐÃ HẾT HẠN từ {exp_date.isoformat()} ({abs(days_left)} ngày trước) — nguy cơ mất chính sách 0 ngày lưu / data training"
    elif days_left == 0:
        state = "on"
        msg = f"DeepSeek ZDR hết hạn HÔM NAY ({exp_date.isoformat()}) — chính sách ZDR kết thúc trong ngày"
    elif days_left <= soon_days:
        state = "soon"
        msg = f"DeepSeek ZDR sắp hết hạn vào {exp_date.isoformat()} (còn {days_left} ngày)"
    elif not renewal_verified:
        state = "renewal_unverified"
        msg = f"DeepSeek ZDR hạn {exp_date.isoformat()} chưa được xác minh gia hạn (còn {days_left} ngày)"
    else:
        state = "ok"
        msg = f"DeepSeek ZDR có hiệu lực đến {exp_date.isoformat()} (còn {days_left} ngày, đã xác minh gia hạn)"

    if state != "ok" and not renewal_verified:
        msg += " — gia hạn chưa được xác minh (unverified renewal)"

    should_alert = (state in ("soon", "on", "expired", "renewal_unverified"))

    return {
        "vendor": "deepseek",
        "expiry": exp_date.isoformat(),
        "today": today.isoformat(),
        "days_left": days_left,
        "state": state,
        "renewal_verified": bool(renewal_verified),
        "should_alert": should_alert,
        "message": msg,
    }

def check_zdr_alert_needed(current_zdr: dict, last_alert_data: dict) -> bool:
    """Dedupe alert theo state:
    Chỉ alert khi state thuộc ('soon', 'on', 'expired', 'renewal_unverified')
    VÀ state khác với last_zdr_state đã gửi thành công trước đó."""
    if not current_zdr.get("should_alert"):
        return False
    current_state = current_zdr.get("state")
    last_zdr_state = (last_alert_data or {}).get("zdr_state")
    if current_state == last_zdr_state:
        return False
    return True

def format_zdr_alert_part(zdr_info: dict) -> str:
    state = zdr_info.get("state")
    expiry = zdr_info.get("expiry", DEEPSEEK_ZDR_EXPIRY)
    days_left = zdr_info.get("days_left")
    verified = zdr_info.get("renewal_verified", False)
    unv_str = "" if verified else " (chưa xác minh gia hạn)"

    if state == "soon":
        days_str = f", còn {days_left} ngày" if days_left is not None else ""
        return f"DeepSeek ZDR sắp hết hạn {expiry}{days_str}{unv_str}"
    elif state == "on":
        return f"DeepSeek ZDR hết hạn HÔM NAY {expiry}{unv_str}"
    elif state == "expired":
        return f"DeepSeek ZDR ĐÃ HẾT HẠN từ {expiry}{unv_str}"
    elif state == "renewal_unverified":
        return f"DeepSeek ZDR hạn {expiry} chưa được xác minh gia hạn"
    return zdr_info.get("message") or f"DeepSeek ZDR alert ({state})"

def format_alert(changes: list[dict], zdr_info: dict | None = None) -> str:
    parts = []
    for c in changes:
        v = c.get("vendor", "")
        t = c.get("type", "")
        if t == "appeared":
            parts.append(f"{v} appeared")
        elif t == "disappeared":
            parts.append(f"{v} disappeared")
        elif t == "version":
            parts.append(f"{v} version {c.get('old')}→{c.get('new')}")
        elif t == "state":
            parts.append(f"{v} {c.get('old')}→{c.get('new')}")
        elif t == "models":
            added_cnt = len(c.get("added", []))
            removed_cnt = len(c.get("removed", []))
            model_parts = []
            if added_cnt > 0:
                model_parts.append(f"+{added_cnt}")
            if removed_cnt > 0:
                model_parts.append(f"-{removed_cnt}")
            cnt_str = "/".join(model_parts)
            suffix = "model" if (added_cnt + removed_cnt) == 1 else "models"
            parts.append(f"{v} {cnt_str} {suffix}")
        elif t == "zdr_expiry":
            parts.append(format_zdr_alert_part(c))

    if zdr_info and zdr_info.get("should_alert"):
        zdr_part = format_zdr_alert_part(zdr_info)
        if zdr_part and zdr_part not in parts:
            parts.append(zdr_part)

    return f"🔔 polykit: {'; '.join(parts)}"

def load_json(path) -> dict:
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def render_snapshot(state: dict, now: str) -> str:
    """Bảng catalog do MÁY sinh — chống trôi docs.
    Additive: hiển thị metadata provenance, timestamp, stale, và advisory."""
    lines = [
        "# Snapshot vendor — MÁY SINH, ĐỪNG SỬA TAY",
        "",
        f"> Sinh lúc {now} bởi `bin/watcher.py --snapshot`. Mỗi lần chạy ghi đè toàn bộ.",
        "> Sai lệch với thực tế = watcher chưa chạy, không phải docs sai.",
        "",
        "| Vendor | State | Version | Số model | Ghi chú |",
        "|---|---|---|---|---|",
    ]
    vendors = state.get("vendors", {}) if isinstance(state, dict) else {}
    for name in vendors:
        v = vendors[name] or {}
        models = v.get("models") or []
        notes = []
        if v.get("error"):
            notes.append(str(v.get("error")))
        if v.get("stale"):
            notes.append("stale (last-known-good)")
        note_str = " | ".join(notes)
        lines.append(
            f"| `{name}` | {v.get('state')} | {v.get('cli_version') or '—'} "
            f"| {len(models) if models else '—'} | {note_str} |"
        )
    for name in vendors:
        v = vendors[name] or {}
        models = v.get("models") or []
        if not models:
            continue
        meta_parts = []
        source = v.get("catalog_source") or v.get("provenance")
        if source:
            meta_parts.append(f"nguồn: {source}")
        ts = v.get("catalog_timestamp") or v.get("timestamp")
        if ts:
            meta_parts.append(f"thời điểm: {ts}")
        if v.get("stale"):
            meta_parts.append("trạng thái: stale")
        meta_str = f" — {', '.join(meta_parts)}" if meta_parts else ""
        lines += ["", f"## Catalog `{name}` ({len(models)} slug{meta_str})", ""]
        for m in models:
            adv = get_model_advisory(m)
            adv_str = f" *({adv})*" if adv else ""
            lines.append(f"- `{m}`{adv_str}")
    lines.append("")
    return "\n".join(lines)
