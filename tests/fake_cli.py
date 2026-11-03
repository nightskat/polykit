"""Vendor CLI GIẢ cho test subprocess — KHÔNG gọi vendor thật.

`make_fake_agy(tmp_path)` tạo thư mục bin/ chứa một `agy` giả (Python) và trả
env đã đặt PATH = bin giả + thư mục python (không có vendor thật nào khác).

Hành vi `agy -p|--print <prompt>` điều khiển bằng chỉ thị trong prompt:
  WRITE:<path>   ghi file <path> (tương đối theo cwd tiến trình)
  CLAIM_ONLY     in "đã ghi xong" nhưng KHÔNG ghi gì (thành công giả)
  READ:<name>    in nội dung <name> trong cwd, hoặc "MISSING:<cwd>"
  FAIL           in lỗi ra stderr, exit 1
  SILENT         chỉ in banner ra stderr, stdout RỖNG, exit 0 (QUAN SÁT-4)
Mỗi lần được gọi, ghi argv + cwd vào $FAKE_AGY_LOG (nếu có).
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

_SCRIPT = r'''#!{py}
import json, os, sys
from pathlib import Path
log = os.environ.get("FAKE_AGY_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd()}}) + "\n")
a = sys.argv[1:]
if a[:1] == ["--version"]:
    print("agy 0.0.0-fake"); sys.exit(0)
if a[:1] == ["models"]:
    print("gemini-3.8-flash-high"); sys.exit(0)
flag = "-p" if "-p" in a else ("--print" if "--print" in a else None)
prompt = a[a.index(flag) + 1] if flag else sys.stdin.read()
if prompt.startswith("/"):
    print("model: gemini-3.8-flash-high (fake doctor stdout)"); sys.exit(0)
if "FAIL" in prompt:
    sys.stderr.write("fake agy: boom\n"); sys.exit(1)
out = []
for tok in prompt.split():
    if tok.startswith("WRITE:"):
        Path(tok[6:]).write_text("artifact từ agy giả\n", encoding="utf-8")
        out.append("đã ghi " + tok[6:])
    elif tok.startswith("READ:"):
        p = Path(tok[5:])
        out.append(p.read_text(encoding="utf-8").strip() if p.exists() else "MISSING:" + os.getcwd())
if "CLAIM_ONLY" in prompt:
    out.append("đã ghi xong file theo yêu cầu")
if "SILENT" in prompt:
    sys.stderr.write("fake agy: banner, không có kết quả\n"); sys.exit(0)
print("\n".join(out) or "OK")
'''


def make_fake_agy(tmp_path: Path) -> dict:
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    exe = bindir / "agy"
    exe.write_text(_SCRIPT.format(py=sys.executable), encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env = dict(os.environ)
    # Chỉ bin giả + coreutils cơ bản (sh cho shell=True) — không vendor thật nào.
    env["PATH"] = os.pathsep.join([str(bindir), "/usr/bin", "/bin"])
    env["FAKE_AGY_LOG"] = str(tmp_path / "agy-calls.jsonl")
    env.pop("XCLI_DISPATCH_DEPTH", None)
    return env


def read_calls(env: dict) -> list[dict]:
    import json
    p = Path(env["FAKE_AGY_LOG"])
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
