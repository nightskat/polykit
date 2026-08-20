from __future__ import annotations
import json
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
    # Model THẬT đã chạy, khi biết được. `model` là thứ ĐÃ YÊU CẦU — với `auto`
    # hoặc router OR thì hai giá trị này khác nhau, và chênh lệch chi phí có thể
    # gấp trăm lần. None = vendor không cho biết (vd codex auto).
    served_model: str | None = None

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

def build_codex_cmd(model: str, sandbox: str, workdir: str | None, fmt: str,
                    stream: bool = False) -> list[str]:
    cmd = ["codex", "exec"]
    if model != "auto":
        cmd.extend(["-m", model])
    cmd.extend(["-s", sandbox])
    # --json vừa là JSONL stream vừa là --format json của codex; stream diagnose
    # dùng lại chính cờ này nên `stream or fmt == "json"`.
    if stream or fmt == "json":
        cmd.append("--json")
    if workdir:
        cmd.extend(["-C", workdir])
    # Luon them --skip-git-repo-check, KE CA khi co -C: codex tu choi chay trong
    # thu muc khong phai git repo ("Not inside a trusted directory"). Truoc day co
    # trong nhanh else -> moi lan dung --cd tro toi thu muc khong-git deu exit 1.
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

def build_grok_cmd(model: str, sandbox: str, workdir: str | None, fmt: str,
                   prompt_file: str, stream: bool = False) -> list[str]:
    grok_bin = str(Path.home() / ".grok/bin/grok")
    cmd = [grok_bin, "--prompt-file", prompt_file]
    if model != "auto":
        cmd.extend(["-m", model])
    # streaming-json là chế độ stream ĐÃ LIVE TEST (4790 byte khi bị giết 20s).
    # json là --format json thường. Stream diagnose ưu tiên streaming-json.
    if stream:
        cmd.extend(["--output-format", "streaming-json"])
    elif fmt == "json":
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

# Model mặc định của lane agy khi gọi `auto`. GIỮ ĐÚNG default sẵn có của
# ~/scripts/agy.sh (3.6 Flash Medium) — Grok P1: đổi default ngầm là phá kỳ vọng
# của mọi lệnh đang chạy, và tier `-high` đốt quota im lặng.
AGY_DEFAULT_MODEL = "gemini-3.6-flash-medium"


def build_agy_cmd(model: str, prompt: str, stream: bool = False) -> list[str]:
    """Gọi THẲNG binary agy, không qua agy.sh — wrapper chỉ có 8 tier Gemini,
    trong khi agy còn phục vụ claude-*/gpt-oss-*.

    stream → --output-format stream-json (cờ TOÀN CỤC, phải đặt TRƯỚC lệnh con
    -p/--print — xem trap 'agy models --output-format json → exit 1')."""
    slug = AGY_DEFAULT_MODEL if model == "auto" else model
    if stream:
        return ["agy", "--output-format", "stream-json", "--model", slug, "-p", prompt]
    return ["agy", "--model", slug, "-p", prompt]


def gemini_agy_tier(model: str) -> str:
    # 3.1 Pro
    if model.startswith("gemini-3.1-pro"):
        return "pro-high" if model.endswith("high") else "pro-low"
    # 3.5 Flash — quota-friendly, explicit opt-in (route to f35 tiers)
    if model.startswith("gemini-3.5-flash"):
        if model.endswith("high"):
            return "f35-high"
        if model.endswith("low"):
            return "f35-low"
        return "f35"
    # 3.6 Flash (newest) + auto default + bare effort suffixes
    if model.endswith("high"):
        return "high"
    if model.endswith("low"):
        return "low"
    return "med"


# 🔴 deepseek-v4-flash TRẢ VỀ RỖNG trên task nhiều bước — vendors.json ghi
# default_model = flash nhưng dispatch PHẢI override auto → pro.
DSH_DEFAULT_MODEL = "deepseek-v4-pro"


def build_dsh_cmd(model: str, patch_file: str) -> list[str]:
    """Tạo command line cho dsh.

    dsh KHÔNG có cờ --model. Phải viết file patch YAML rồi truyền --patch.
    patch_file do caller tạo (tempfile) với nội dung:
    - id: agent-default-model
      config: {provider: deepseek-official, model: <slug>}
    """
    cmd = ["dsh", "--profile", "headless"]
    if model != "auto":
        cmd.extend(["--patch", patch_file])
    return cmd


def write_dsh_patch(model_slug: str, path: str) -> None:
    """Ghi file YAML patch cho dsh --patch. Chỉ dùng stdlib (yaml đơn giản)."""
    content = (
        f"- id: agent-default-model\n"
        f"  config: {{provider: deepseek-official, model: {model_slug}}}\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# Key trong event stream mang NỘI DUNG trợ lý. Cố ý KHÔNG gồm type/role/status —
# nếu không chuỗi nhãn "thought" sẽ lẫn vào văn bản trích.
_STREAM_TEXT_KEYS = ("text", "thought", "reasoning", "content", "delta", "message")


# Event KHÔNG phải chữ trợ lý — bỏ nguyên cả event, đừng moi chữ trong đó.
# Đo thật 20/08: codex --json phát `{"type":"item.completed","item":{"type":"error",
# "message":"clamping SessionEnd hook timeout..."}}`; gom bừa thì log lỗi hạ tầng
# bị trích ra thành "chữ trợ lý" (Codex review).
_STREAM_SKIP_TYPES = ("error", "tool", "user", "command", "available_commands")


def _bo_qua_event(node) -> bool:
    if not isinstance(node, dict):
        return False
    t = node.get("type")
    if isinstance(t, str) and any(k in t.lower() for k in _STREAM_SKIP_TYPES):
        return True
    r = node.get("role")
    return isinstance(r, str) and r.lower() in ("user", "tool", "system")


def _collect_stream_text(node, out: list[str]) -> None:
    """Đệ quy gom chuỗi chữ hữu ích từ một object JSON của event stream."""
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, list):
        for item in node:
            _collect_stream_text(item, out)
    elif isinstance(node, dict):
        if _bo_qua_event(node):
            return
        for key in _STREAM_TEXT_KEYS:
            if key in node:
                _collect_stream_text(node[key], out)
        # Event bọc ngoài (vd codex: {"type":"item.completed","item":{...}}) —
        # đi tiếp vào trong, nhưng vẫn tôn trọng bộ lọc ở mỗi tầng.
        for key in ("item", "event", "data", "payload"):
            if key in node:
                _collect_stream_text(node[key], out)


def extract_stream_text(raw: str) -> str:
    """Trích phần chữ của trợ lý từ output stream JSONL thô (hàm THUẦN).

    Mỗi dòng là một event JSON. Dòng JSON DỞ DANG ở cuối (bị giết giữa chừng)
    thì BỎ QUA chứ KHÔNG nổ. Không trích được gì → trả "" để caller giữ nguyên
    thô, không làm mất dữ liệu.
    """
    out: list[str] = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            # Dòng dở dang / không phải JSON → bỏ qua, không làm chết cả hàm.
            continue
        _collect_stream_text(obj, out)
    return "\n".join(p for p in out if p and p.strip())

