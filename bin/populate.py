#!/usr/bin/env python3
"""populate.py — giữ PolyKit đồng bộ trên MỌI vendor CLI.

Vấn đề nó giải: adapter cho từng vendor trước đây viết tay một lần rồi trôi.
Đo 19/08/2026: Claude ghim ở commit 03/08, Codex ghim ở bản 14/07, Gemini
dùng extension 05/05 không gọi PolyKit dòng nào.

Nguồn sự thật DUY NHẤT = repo này (`commands/*.md` + `.claude-plugin/plugin.json`).
Mọi adapter đều được SINH RA, không sửa tay.

    python3 bin/populate.py            # --check: in bảng, không đổi gì
    python3 bin/populate.py --apply    # sinh adapter + gọi lệnh update của từng CLI

Claude ghim bản chạy theo gitCommitSha (cache), nên nó cần `claude plugin update`.
Codex/Gemini thì adapter chỉ là CHỮ, còn engine gọi thẳng dispatch.py trong repo —
sửa repo là chúng ăn ngay, không có gì để ghim.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DISPATCH = REPO / "bin" / "dispatch.py"
HOME = Path.home()

CODEX_PLUGIN_DIR = HOME / "plugins" / "polykit"
GEMINI_EXT_DIR = HOME / ".gemini" / "extensions" / "polykit"
CLAUDE_INSTALLED = HOME / ".claude" / "plugins" / "installed_plugins.json"

BANNER = "<!-- SINH TỰ ĐỘNG bởi bin/populate.py — ĐỪNG SỬA TAY, sửa commands/*.md trong repo PolyKit -->"


def repo_version() -> str:
    return json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())["version"]


def repo_head() -> str:
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def commands() -> dict[str, str]:
    """Đọc commands/*.md của repo, bỏ frontmatter, trả {tên: thân}."""
    out = {}
    for f in sorted((REPO / "commands").glob("*.md")):
        text = f.read_text(encoding="utf-8")
        body, desc = text, ""
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end != -1:
                fm, body = text[3:end], text[end + 4:]
                for line in fm.splitlines():
                    if line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip().strip('"')
        out[f.stem] = (desc, body.strip())
    return out


def skill_md(name: str, desc: str, body: str) -> str:
    body = body.replace('${CLAUDE_PLUGIN_ROOT}/bin/dispatch.py', str(DISPATCH))
    return f"""---
name: {name}
description: {desc}
---
{BANNER}

# PolyKit {name}

{body}
"""


# ── các đích ────────────────────────────────────────────────────────────────

def plan_codex(cmds) -> dict[Path, str]:
    files = {CODEX_PLUGIN_DIR / ".codex-plugin" / "plugin.json": json.dumps({
        "name": "polykit",
        "version": f"{repo_version()}+codex.local",
        "description": "Multi-vendor CLI toolkit: dispatch, quota failover, and vendor-state monitoring.",
        "author": {"name": "Tuan Khuc", "email": "nightskat@gmail.com"},
        "skills": "./skills/",
        "interface": {
            "displayName": "PolyKit",
            "shortDescription": "Dispatch and monitor multiple AI CLI vendors.",
            "longDescription": "Local adapter for PolyKit's dispatch, diagnostic, failover, and watcher workflows.",
            "developerName": "Tuan Khuc",
            "category": "Productivity",
            "capabilities": ["Interactive", "Write"],
            "brandColor": "#2563EB",
        },
    }, ensure_ascii=False, indent=2) + "\n"}
    for name, (desc, body) in cmds.items():
        files[CODEX_PLUGIN_DIR / "skills" / name / "SKILL.md"] = skill_md(name, desc, body)
    return files


def plan_gemini(cmds) -> dict[Path, str]:
    files = {GEMINI_EXT_DIR / "gemini-extension.json": json.dumps({
        "name": "polykit",
        "description": "PolyKit: dispatch task tới vendor CLI khác, doctor, failover, watcher.",
        "version": repo_version(),
        "contextFileName": "GEMINI.md",
    }, ensure_ascii=False, indent=2) + "\n"}
    files[GEMINI_EXT_DIR / "GEMINI.md"] = f"""# PolyKit (bản Gemini)
{BANNER}

Bạn gọi PolyKit để giao việc sang vendor CLI khác, xem trạng thái quota, và failover.
Engine nằm ở `{DISPATCH}` — luôn là bản mới nhất của repo, không có bản chép nào để trôi.

```bash
python3 {DISPATCH} <vendor> [model] --prompt-file <path> --result-json
```

Vendor đọc từ `{REPO / 'config' / 'vendors.json'}` — đừng đoán tên, đừng hardcode model.

⛔ **KHÔNG dispatch sang `claude`** từ lane Gemini: vi phạm ToS. Xem `docs/CHIA-VIEC.md`.
⛔ **KHÔNG gửi PII thật** (tên/CIF/MST/số dư khách hàng) qua bất kỳ vendor nào.
"""
    for name, (desc, body) in cmds.items():
        files[GEMINI_EXT_DIR / "commands" / f"{name}.md"] = f"""---
description: {desc}
---
{BANNER}

{body.replace('${CLAUDE_PLUGIN_ROOT}/bin/dispatch.py', str(DISPATCH))}
"""
        files[GEMINI_EXT_DIR / "skills" / name / "SKILL.md"] = skill_md(name, desc, body)
    return files


def claude_state() -> tuple[str, str]:
    """(version đang chạy, sha đang chạy) của plugin Claude Code."""
    try:
        d = json.loads(CLAUDE_INSTALLED.read_text())["plugins"]["polykit@polykit"][0]
        return d.get("version", "?"), d.get("gitCommitSha", "")
    except Exception:
        return "chưa cài", ""


def grok_sha() -> str:
    """SHA bản grok ĐANG CÀI — grok chép code về, không trỏ vào repo, nên nó TRÔI."""
    if not shutil.which("grok"):
        return ""
    r = subprocess.run(["grok", "plugin", "list"], capture_output=True, text=True)
    if "polykit" not in r.stdout:
        return ""
    for d in (HOME / ".grok" / "installed-plugins").glob("polykit-*"):
        f = d / "bin" / "lib" / "dispatch_core.py"
        if f.exists():
            local = (REPO / "bin" / "lib" / "dispatch_core.py").read_text(encoding="utf-8")
            return "khớp" if f.read_text(encoding="utf-8") == local else "cũ"
    return "?"


def agy_has_polykit() -> bool:
    """agy không có marketplace riêng — nó IMPORT extension của gemini-cli."""
    if not shutil.which("agy"):
        return False
    r = subprocess.run(["agy", "plugin", "list"], capture_output=True, text=True)
    return "polykit" in r.stdout


def diff_files(files: dict[Path, str]) -> list[Path]:
    return [p for p, c in files.items()
            if not p.exists() or p.read_text(encoding="utf-8") != c]


def write_files(files: dict[Path, str]) -> None:
    for p, c in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(c, encoding="utf-8")


def run(cmd: list[str]) -> str:
    if not shutil.which(cmd[0]):
        return f"⚠ chưa cài {cmd[0]}"
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else f"exit {r.returncode}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Đồng bộ PolyKit sang mọi vendor CLI")
    ap.add_argument("--apply", action="store_true", help="Sinh adapter và chạy lệnh update; mặc định chỉ kiểm tra")
    args = ap.parse_args()

    cmds = commands()
    ver, head = repo_version(), repo_head()
    print(f"Repo: v{ver} @ {head[:7]}  ({len(cmds)} lệnh: {', '.join(cmds)})\n")

    codex_files, gemini_files = plan_codex(cmds), plan_gemini(cmds)
    codex_drift, gemini_drift = diff_files(codex_files), diff_files(gemini_files)
    c_ver, c_sha = claude_state()

    rows = [
        ("claude", f"v{c_ver} @ {c_sha[:7] or '—'}",
         "✅ khớp" if c_sha == head else "🔴 LỆCH — cache ghim theo sha"),
        ("codex", str(CODEX_PLUGIN_DIR),
         "✅ khớp" if not codex_drift else f"🔴 LỆCH {len(codex_drift)} file"),
        ("gemini", str(GEMINI_EXT_DIR),
         "✅ khớp" if not gemini_drift else f"🔴 LỆCH {len(gemini_drift)} file"),
        ("grok", "bản chép từ GitHub (TRÔI được)",
         {"khớp": "✅ khớp", "cũ": "🔴 LỆCH — cần `grok plugin update`",
          "": "🔴 CHƯA CÀI"}.get(grok_sha(), "⚠️ không đọc được")),
        ("agy", "import từ extension của gemini-cli",
         "✅ đã import" if agy_has_polykit() else "🔴 CHƯA IMPORT"),
    ]
    w = max(len(r[1]) for r in rows)
    for name, where, status in rows:
        print(f"  {name:<8} {where:<{w}}  {status}")

    if not args.apply:
        print("\n(chỉ kiểm tra — thêm --apply để sửa)")
        return 0

    print("\n── áp dụng ──")
    write_files(codex_files)
    print(f"  codex   ghi {len(codex_files)} file → {CODEX_PLUGIN_DIR}")
    write_files(gemini_files)
    print(f"  gemini  ghi {len(gemini_files)} file → {GEMINI_EXT_DIR}")
    print("  claude  " + run(["claude", "plugin", "marketplace", "update", "polykit"]))
    print("  claude  " + run(["claude", "plugin", "update", "polykit@polykit"]))
    if grok_sha() == "":
        print("  grok    " + run(["grok", "plugin", "install", "nightskat/polykit", "--trust"]))
    else:
        # `grok plugin update` kéo từ GitHub → chỉ thấy commit ĐÃ PUSH.
        print("  grok    " + run(["grok", "plugin", "update"]))
    # agy đọc extension của gemini-cli, nên phải chạy SAU khi ghi thư mục gemini.
    print("  agy     " + run(["agy", "plugin", "import", "gemini"]))
    print("\n⚠️ Claude Code cần RESTART thì bản mới mới có hiệu lực.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
