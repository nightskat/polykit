import json
import pathlib
from pathlib import Path
import platformdirs
from lib.states import VendorProbe, classify
from lib.vendors import REGISTRY

SCHEMA_VERSION = 1

def state_path() -> Path:
    return Path(platformdirs.user_state_dir("polykit")) / "state.json"

def build_state(probes: list[VendorProbe], now: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "vendors": {
            p.name: {
                "state": classify(p).value,
                "cli_path": p.path,
                "cli_version": p.version,
                "models": p.models,
                "error": p.error,
                "binary": REGISTRY[p.name].binary if p.name in REGISTRY else p.name,
                "auth_hint": REGISTRY[p.name].auth_hint if p.name in REGISTRY else "",
            }
            for p in probes
        }
    }

def write_state(state: dict, path=None) -> Path:
    if path is None:
        path = state_path()
    else:
        path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return path

def read_state(path=None) -> dict | None:
    if path is None:
        path = state_path()
    else:
        path = Path(path)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # State là cache regenerate được — file hỏng thì coi như chưa có.
        return None
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
        return None
    return state
