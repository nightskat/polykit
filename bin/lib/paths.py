"""Path resolution — platformdirs nếu có, KHÔNG có thì fallback stdlib.

MVP blocker (2026-07-13): plugin cài trên máy dùng system python3 (không có
platformdirs) sẽ chết nếu import cứng. Spec P5 = tối thiểu dep + cross-platform
bằng thiết kế → platformdirs thành OPTIONAL, stdlib lo 3 nền tảng.

Fallback phải KHỚP platformdirs để máy có/không có dep dùng CÙNG state path
(Codex MVP review): appauthor=False (Windows khỏi nhân đôi polykit\\polykit),
honor XDG_STATE_HOME (platformdirs honor cả trên macOS — đã verify)."""
from __future__ import annotations
import os
import sys
from pathlib import Path


def user_state_dir(app: str) -> str:
    try:
        import platformdirs
    except ImportError:
        # Chỉ fallback khi THIẾU dep — lỗi thật của platformdirs không nuốt (Codex #3).
        return _fallback_state_dir(app)
    # appauthor=False để khớp fallback (Windows mặc định thêm appauthor=appname).
    return platformdirs.user_state_dir(app, appauthor=False)


def _fallback_state_dir(app: str) -> str:
    home = Path.home()
    # XDG_STATE_HOME thắng trên mọi nền (platformdirs honor cả macOS — verified).
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return str(Path(xdg) / app)
    if sys.platform == "darwin":
        return str(home / "Library" / "Application Support" / app)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return str(Path(base) / app)
    return str(home / ".local" / "state" / app)
