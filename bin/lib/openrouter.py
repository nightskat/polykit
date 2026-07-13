from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path

OR_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
OR_KEY_ENVS = ["OPENROUTER_API_KEY", "OR_API_KEY"]
OR_KEY_FILES = [Path.home() / ".config/openrouter/key", Path.home() / ".openrouter/key"]
# Free model OpenRouter XOAY VÒNG thường xuyên (model cũ bị gỡ → 404, provider busy → 429).
# Giá trị này verify sống 2026-07-13; hết hạn thì đổi, hoặc truyền model tường minh khi dispatch.
# TODO(backlog): "auto" nên tự chọn 1 model :free còn sống qua /models thay vì hardcode.
DEFAULT_FREE_MODEL = "nvidia/nemotron-3-nano-30b-a3b:free"

@dataclass
class ORResult:
    ok: bool
    text: str = ""
    error: str | None = None
    quota_capped: bool = False
    http_code: int | None = None

def get_or_key(env: dict[str, str] | None = None) -> str | None:
    if env is None:
        env = os.environ
    # Codex OR #1/#2: strip + chỉ nhận key non-empty (whitespace ≠ key hợp lệ),
    # file rỗng thì fallback sang file sau.
    for env_var in OR_KEY_ENVS:
        val = (env.get(env_var) or "").strip()
        if val:
            return val
    for file_path in OR_KEY_FILES:
        try:
            if file_path.exists():
                val = file_path.read_text(encoding="utf-8").strip()
                if val:
                    return val
        except Exception:
            pass
    return None

def or_dispatch(
    prompt: str,
    model: str = "auto",
    timeout: int = 120,
    key: str | None = None,
    opener: any = None,
) -> ORResult:
    if key is None:
        key = get_or_key()
    if not key:
        return ORResult(ok=False, error="no OPENROUTER_API_KEY")

    if opener is None:
        opener = urllib.request.urlopen

    m = DEFAULT_FREE_MODEL if model == "auto" else model
    body = json.dumps({"model": m, "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/nightskat/polykit",
        "X-Title": "polykit",
    }
    req = urllib.request.Request(OR_ENDPOINT, data=body, headers=headers, method="POST")

    try:
        resp = opener(req, timeout=timeout)
        data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"]
        return ORResult(ok=True, text=text)
    except urllib.error.HTTPError as e:
        code = e.code
        body_txt = ""
        try:
            body_txt = e.read().decode("utf-8")
        except Exception:
            pass
        finally:
            try:
                e.close()
            except Exception:
                pass
        quota = code in (402, 429) or any(w in body_txt.lower() for w in ["quota", "rate", "exhaust"])
        return ORResult(ok=False, error=f"HTTP {code}", quota_capped=quota, http_code=code)
    except Exception as e:
        return ORResult(ok=False, error=str(e))
