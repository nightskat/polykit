from __future__ import annotations
import json
from lib.paths import user_state_dir
from pathlib import Path
from datetime import datetime, timezone

def evidence_path() -> Path:
    return Path(user_state_dir("polykit")) / "dispatch-log.jsonl"

def append_evidence(record: dict, path=None) -> bool:
    if path is None:
        path = evidence_path()
    else:
        path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False

def make_record(vendor: str, model: str, status: str, now: str, reason: str | None = None, latency_ms: int | None = None) -> dict:
    return {
        "ts": now,
        "vendor": vendor,
        "model": model,
        "status": status,
        "reason": reason,
        "latency_ms": latency_ms
    }

def read_evidence(limit: int = 20, path=None) -> list[dict]:
    if path is None:
        path = evidence_path()
    else:
        path = Path(path)
    if not path.is_file():
        return []
    try:
        records = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
        return records[-limit:] if limit > 0 else []
    except Exception:
        return []
