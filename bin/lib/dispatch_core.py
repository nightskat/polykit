import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

class DispatchError(Exception):
    """Raised when dispatch guards or validation checks fail."""
    pass

@dataclass
class DispatchResult:
    status: str  # "ok", "skipped", "error", "timeout", "blocked"
    vendor: str
    model: str
    summary: str
    warnings: list[str] = field(default_factory=list)
    stdout: str = ""
    exit_code: int | None = None
    reason: str | None = None

    def __post_init__(self):
        # P4: mọi trạng thái non-ok phải có exit_code + reason cụ thể, không null.
        _defaults = {
            "ok": (0, None),
            "error": (1, "vendor_exit_nonzero"),
            "timeout": (124, "timeout"),
            "blocked": (1, "guard_violation"),
            "skipped": (1, "skipped"),
        }
        d_exit, d_reason = _defaults.get(self.status, (1, self.status))
        if self.exit_code is None:
            self.exit_code = d_exit
        if self.status != "ok" and self.reason is None:
            self.reason = d_reason

    def to_dict(self) -> dict:
        return asdict(self)

def validate_timeout(t) -> int:
    try:
        val = int(t)
    except (ValueError, TypeError):
        raise DispatchError(f"timeout must be a positive integer, got: {t!r}")
    if not (1 <= val <= 600):
        raise DispatchError(f"timeout must be a positive integer 1-600, got: {val}")
    return val

def validate_sandbox(s) -> str:
    if s not in ("read-only", "workspace-write"):
        raise DispatchError(f"sandbox must be read-only or workspace-write, got: {s!r}")
    return s

def build_codex_cmd(model: str, sandbox: str, workdir: str | None, fmt: str) -> list[str]:
    cmd = ["codex", "exec"]
    if model != "auto":
        cmd.extend(["-m", model])
    cmd.extend(["-s", sandbox])
    if fmt == "json":
        cmd.append("--json")
    if workdir:
        cmd.extend(["-C", workdir])
    else:
        cmd.append("--skip-git-repo-check")
    return cmd

def build_claude_cmd(model: str, prompt: str) -> list[str]:
    cmd = ["claude"]
    if model != "auto":
        cmd.extend(["--model", model])
    # Mandatory ToS-bounded options (P3)
    cmd.extend([
        "--effort", "low",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--tools", "",
        "--permission-mode", "plan"
    ])
    cmd.extend(["-p", prompt])
    return cmd

def build_grok_cmd(model: str, sandbox: str, workdir: str | None, fmt: str, prompt_file: str) -> list[str]:
    grok_bin = str(Path.home() / ".grok/bin/grok")
    cmd = [grok_bin, "--prompt-file", prompt_file]
    if model != "auto":
        cmd.extend(["-m", model])
    if fmt == "json":
        cmd.extend(["--output-format", "json"])
    if workdir:
        cmd.extend(["--cwd", workdir])
    if sandbox == "workspace-write":
        cmd.extend([
            "--disallowed-tools", "run_terminal_cmd,web_search,web_fetch,task,Agent",
            "--permission-mode", "acceptEdits"
        ])
    else:
        cmd.extend([
            "--tools", "read_file,grep,list_dir",
            "--always-approve"
        ])
    return cmd

def gemini_agy_tier(model: str) -> str:
    if model.startswith("gemini-3.1-pro") and model.endswith("high"):
        return "pro-high"
    elif model.startswith("gemini-3.1-pro"):
        return "pro-low"
    elif model.endswith("high"):
        return "high"
    elif model.endswith("low"):
        return "low"
    else:
        return "med"
