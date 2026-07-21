from __future__ import annotations
import json
import hashlib
import os
import time
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
    vendors_data = state.get("vendors", {})
    snap = {}
    for vendor, vdata in vendors_data.items():
        snap[vendor] = {
            "models": sorted(list(vdata.get("models") or [])),
            "version": vdata.get("cli_version"),
            "state": vdata.get("state"),
            "error": vdata.get("error"),
        }
    return snap

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

def format_alert(changes: list[dict]) -> str:
    parts = []
    for c in changes:
        v = c["vendor"]
        t = c["type"]
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
    return f"🔔 polykit: {'; '.join(parts)}"

OR_MODELS_API = "https://openrouter.ai/api/v1/models"

def fetch_or_free_models(timeout: int = 15) -> list[str] | None:
    """Lấy danh sách model free trên OpenRouter (pricing.prompt == "0").
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
    baseline cũ để không alert giả 'removed toàn bộ'."""
    if "openrouter" not in snap:
        return
    ids = fetcher()
    if ids is None:
        old = load_json(baseline_path())
        ids = (old.get("openrouter") or {}).get("models") or []
    snap["openrouter"]["models"] = ids

def is_offline(snapshot: dict) -> bool:
    # Codex M4 #2: offline = detect fail hạ tầng (mọi vendor có error field),
    # KHÔNG phải not_installed. Gỡ vendor thật (not_installed, error=None) vẫn
    # được báo 'disappeared' — không bị mark offline rồi mù vĩnh viễn.
    if not snapshot:
        return True
    return all(v.get("error") for v in snapshot.values())

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
