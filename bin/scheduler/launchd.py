from __future__ import annotations
# cron/schtasks = PARKED (chỉ launchd cho v0.1)
import plistlib
from pathlib import Path

def generate_plist(label: str, program_args: list[str], weekday: int = 0, hour: int = 9, minute: int = 30) -> str:
    # Codex M4 #3: dùng plistlib để escape đúng — path chứa & < > không phá plist.
    data = {
        "Label": label,
        "ProgramArguments": list(program_args),
        "StartCalendarInterval": {"Weekday": weekday, "Hour": hour, "Minute": minute},
        "RunAtLoad": False,
    }
    return plistlib.dumps(data).decode("utf-8")

def plist_path(label: str) -> Path:
    return Path.home() / "Library/LaunchAgents" / f"{label}.plist"

def install(label: str, program_args: list[str], **kw) -> Path:
    path = plist_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    weekday = kw.get("weekday", 0)
    hour = kw.get("hour", 9)
    minute = kw.get("minute", 30)
    
    content = generate_plist(label, program_args, weekday=weekday, hour=hour, minute=minute)
    path.write_text(content, encoding="utf-8")
    return path
