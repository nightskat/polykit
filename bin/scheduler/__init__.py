from __future__ import annotations
"""Scheduler adapter selector — launchd (Mac) / schtasks (Windows).
cron (Linux) vẫn PARKED."""
import os
import sys


def schedule_weekly(label: str, program_args: list[str], weekday: int = 0,
                    hour: int = 9, minute: int = 30) -> dict:
    """Lên lịch chạy hàng tuần, tự chọn adapter theo OS. Trả dict {installed, ...}.
    Non-Mac/Windows (Linux) → chưa hỗ trợ, trả note (cron PARKED)."""
    if sys.platform == "darwin":
        from scheduler.launchd import install as _install
        path = _install(label, program_args, weekday=weekday, hour=hour, minute=minute)
        return {"installed": True, "platform": "darwin", "plist": str(path),
                "note": f"chạy: launchctl load {path}"}
    if os.name == "nt":
        from scheduler.schtasks import install as _install
        return _install(label, program_args, weekday=weekday, hour=hour, minute=minute)
    return {"installed": False, "platform": os.name,
            "note": "Linux cron adapter PARKED — chạy watcher.py thủ công hoặc tự thêm cron"}
