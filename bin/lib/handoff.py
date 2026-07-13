from __future__ import annotations
from lib.paths import user_state_dir
from pathlib import Path

def build_handoff_note(task: str, done: list[str], remaining: list[str], files: list[str], now: str) -> str:
    done_str = "\n".join(f"- {item}" for item in done) if done else "- (chưa có)"
    remaining_str = "\n".join(f"- {item}" for item in remaining) if remaining else "- (chưa có)"
    files_str = "\n".join(f"- {item}" for item in files) if files else "- (chưa có)"
    
    return (
        f"# Handoff — {now}\n"
        f"## Task\n"
        f"{task}\n"
        f"## Đã làm\n"
        f"{done_str}\n"
        f"## Còn lại\n"
        f"{remaining_str}\n"
        f"## Files liên quan\n"
        f"{files_str}\n"
        f"## Cách tiếp\n"
        f"Paste note này vào codex/gemini. Không cần công cụ ngoài."
    )

def write_handoff(note: str, path=None) -> Path:
    if path is None:
        path = Path(user_state_dir("polykit")) / "handoff-latest.md"
    else:
        path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note, encoding="utf-8")
    return path
