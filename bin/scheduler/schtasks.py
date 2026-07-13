from __future__ import annotations

# Đối xứng launchd (Mac); cron adapter vẫn PARKED.

import os
import subprocess
from pathlib import Path

WEEKDAYS = {
    0: "SUN",
    1: "MON",
    2: "TUE",
    3: "WED",
    4: "THU",
    5: "FRI",
    6: "SAT",
}

def format_time(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"

def generate_schtasks_cmd(
    task_name: str,
    program_args: list[str],
    weekday: int = 0,
    hour: int = 9,
    minute: int = 30,
) -> list[str]:
    # Codex OR #3: dùng list2cmdline để escape đúng kiểu Windows (dấu ", backslash,
    # space) thay vì tự bọc ngoặc — tránh action string hỏng với arg như --title=a "b".
    tr = subprocess.list2cmdline(program_args)
    return [
        "schtasks",
        "/Create",
        "/TN",
        task_name,
        "/TR",
        tr,
        "/SC",
        "WEEKLY",
        "/D",
        WEEKDAYS[weekday],
        "/ST",
        format_time(hour, minute),
        "/F",
    ]

def install(
    task_name: str,
    program_args: list[str],
    weekday: int = 0,
    hour: int = 9,
    minute: int = 30,
    runner: any = subprocess.run,
) -> dict:
    cmd = []
    try:
        cmd = generate_schtasks_cmd(task_name, program_args, weekday, hour, minute)
        if os.name == "nt":
            res = runner(cmd, capture_output=True, text=True)
            return {
                "installed": bool(res.returncode == 0),
                "cmd": cmd,
                "platform": "windows",
            }
        else:
            return {
                "installed": False,
                "cmd": cmd,
                "platform": os.name,
                "note": "chạy lệnh này trên Windows để cài",
            }
    except Exception as e:
        platform_name = "windows" if os.name == "nt" else os.name
        return {
            "installed": False,
            "cmd": cmd,
            "platform": platform_name,
            "error": str(e),
        }
