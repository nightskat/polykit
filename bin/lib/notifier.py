import os
import subprocess
from pathlib import Path


def _notifier_path() -> Path:
    """Codex #7: path notifier discoverable — env override trước, rồi fallback
    layout máy hiện tại. Máy mới set POLYKIT_NOTIFIER trỏ script tg-ping của mình."""
    env = os.environ.get("POLYKIT_NOTIFIER")
    if env:
        return Path(env)
    return Path.home() / "Claude/scripts/tg-ping.sh"


def default_notifier(message: str, silent: bool = False) -> bool:
    script_path = _notifier_path()
    if not script_path.exists():
        return False
    
    cmd = [str(script_path), message]
    if silent:
        cmd.append("--silent")
        
    try:
        res = subprocess.run(cmd, timeout=15, capture_output=True, text=True)
        return res.returncode == 0
    except Exception:
        return False
