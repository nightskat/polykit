"""Path resolution — platformdirs nếu có, KHÔNG có thì fallback stdlib.

MVP blocker (2026-07-13): plugin cài trên máy dùng system python3 (không có
platformdirs) sẽ chết nếu import cứng. Spec P5 = tối thiểu dep + cross-platform
bằng thiết kế → platformdirs thành OPTIONAL, stdlib lo 3 nền tảng."""
from __future__ import annotations
import os
import sys
from pathlib import Path


def user_state_dir(app: str) -> str:
    try:
        import platformdirs
        return platformdirs.user_state_dir(app)
    except Exception:
        return _fallback_state_dir(app)


def _fallback_state_dir(app: str) -> str:
    home = Path.home()
    if sys.platform == "darwin":
        return str(home / "Library" / "Application Support" / app)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return str(Path(base) / app)
    # linux/unix: XDG_STATE_HOME hoặc ~/.local/state
    base = os.environ.get("XDG_STATE_HOME") or str(home / ".local" / "state")
    return str(Path(base) / app)
