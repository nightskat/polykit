"""OpenRouter lane (HTTP API) — policy TRƯỚC key/network.

Bất biến bảo mật (Plan 2026-10-22 mục 94 + Lô 4/9):
1. `check_model_policy` chạy TRƯỚC mọi key lookup, đọc file key, opener và
   network call. Không có đường nào chạm mạng khi policy đã block.
2. Contributor luôn bị chặn (mọi source, kể cả explicit); `*-free` / `:free`
   chỉ được chọn TƯỜNG MINH và router generic (`auto`, `free`, `:free`) bị
   chặn vì chưa rõ đích thực thi.
3. OpenRouter dùng namespace `org/model` — đó KHÔNG phải provider khác. Selector
   được scope dưới `openrouter/` trước khi parse để giữ compatibility với slug
   dạng `meta-llama/llama-3-8b-instruct`, nhưng policy vẫn nhìn thấy toàn bộ
   chuỗi nên contributor/free bị chặn trước network.
4. `served_model` chỉ lấy từ RESPONSE. Không suy ra "đã phục vụ" từ slug đã
   gửi: requested ≠ served là chuyện thường với router, và chi phí chênh nhau
   rất nhiều.
"""
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
# Model free OpenRouter XOAY VÒNG thường xuyên (model cũ bị gỡ → 404, provider busy → 429).
# Cập nhật 2026-09-07: minimax/minimax-m3:free với reasoning effort high.
# ⚠️ Từ chính sách plan 94, mọi slug `:free` bị policy chặn (chưa xác minh
# privacy/training). Hằng số giữ lại cho doctor/bench đọc, KHÔNG còn là default
# ngầm: `auto` không bao giờ rơi về đây.
DEFAULT_FREE_MODEL = "minimax/minimax-m3:free"
DEFAULT_FREE_EFFORT = "high"


@dataclass
class ORResult:
    ok: bool
    text: str = ""
    error: str | None = None
    quota_capped: bool = False
    http_code: int | None = None
    # Model THẬT đã phục vụ request, CHỈ lấy từ response. Với router
    # (`openrouter/auto`, `fusion`, `free`...) nó khác hẳn model đã yêu cầu —
    # bench 03/08: auto→gemini-2.5-flash-lite, fusion→claude-opus-5 (~$1/lượt
    # khi prompt mở). Không log cái này = mù chi phí.
    served_model: str | None = None
    provider: str | None = None
    reason: str | None = None
    # Slug ĐÃ YÊU CẦU (đã chuẩn hoá, bỏ prefix openrouter/). Tách khỏi
    # served_model để không ai đọc nhầm intent thành kết quả thật.
    requested_model: str | None = None


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
    effort: str | None = None,
    source: any = "explicit",
    allow_unknown: bool = False,
) -> ORResult:
    """Gọi OpenRouter một lượt. Policy-first: không key, không network khi block.

    `source` là NGUỒN GỐC do caller quyết (explicit/default/auto/failover).
    Chỉ khi model là `auto` và caller không nói gì khác thì mới nâng thành AUTO;
    default/failover giữ nguyên để policy free-model áp đúng.
    """
    # 1. Chốt chặn policy TRƯỚC mọi key lookup, opener hay network call
    try:
        from lib.model_policy import check_model_policy, SelectionSource
    except ImportError:
        from bin.lib.model_policy import check_model_policy, SelectionSource

    if not isinstance(model, str) or not model.strip():
        return ORResult(
            ok=False,
            error="model must be a non-empty string",
            reason="malformed_selector",
            http_code=400,
        )

    eff_source = source
    raw_m = model.strip()
    if raw_m.lower() == "auto" and (eff_source == "explicit" or eff_source == SelectionSource.EXPLICIT):
        eff_source = SelectionSource.AUTO

    # Đảm bảo scoped dưới openrouter/ để model_policy nhận diện đúng namespace
    # mà vẫn giữ org/model (không phải provider khác).
    full_target = raw_m if raw_m.lower().startswith("openrouter/") else f"openrouter/{raw_m}"

    decision = check_model_policy(
        selector=full_target,
        vendor="openrouter",
        provider="openrouter",
        source=eff_source,
        allow_unknown=allow_unknown,
    )

    if decision.is_blocked:
        r_reason = decision.reason or "policy_violation"
        msg = decision.warnings[0] if decision.warnings else f"Model policy blocked with reason: {r_reason}"
        return ORResult(
            ok=False,
            error=f"policy blocked: {r_reason} ({msg})",
            reason=r_reason,
            http_code=400,
            requested_model=raw_m,
        )

    # Model đích dùng cho API: bỏ prefix openrouter/ nếu có, giữ nguyên org/model.
    m = decision.selector.model

    # 2. Effort validate TRƯỚC khi đọc key (không tốn I/O, không network)
    raw_eff = effort or decision.selector.variant
    if not raw_eff:
        raw_eff = os.environ.get("OPENROUTER_REASONING_EFFORT") or os.environ.get("OR_EFFORT")
    eff = raw_eff.strip() if isinstance(raw_eff, str) and raw_eff.strip() else None

    if eff:
        try:
            from lib.dispatch_core import EFFORT_HOP_LE
        except ImportError:
            from bin.lib.dispatch_core import EFFORT_HOP_LE
        if eff not in EFFORT_HOP_LE:
            return ORResult(
                ok=False,
                error=f"effort phải là một trong {', '.join(EFFORT_HOP_LE)}, got: {eff!r}",
                reason="invalid_effort",
                requested_model=m,
            )

    # 3. Key check sau khi policy đã thông qua
    if key is None:
        key = get_or_key()
    if not key:
        return ORResult(ok=False, error="no OPENROUTER_API_KEY", reason="no_api_key",
                        requested_model=m)

    if opener is None:
        opener = urllib.request.urlopen

    payload = {"model": m, "messages": [{"role": "user", "content": prompt}]}
    if eff and eff != "none":
        payload["reasoning"] = {"effort": eff}
    body = json.dumps(payload).encode("utf-8")
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
        return ORResult(ok=False, error=f"HTTP {code}", quota_capped=quota,
                        http_code=code, requested_model=m,
                        reason="quota_capped" if quota else "http_error")
    except Exception as e:
        return ORResult(ok=False, error=str(e), reason="exec_error", requested_model=m)

    # 4. Parse response — served chỉ có ở đây, không suy từ slug đã gửi.
    if not isinstance(data, dict):
        return ORResult(ok=False, error="response is not a JSON object",
                        reason="bad_response", requested_model=m)
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ORResult(ok=False, error="response missing choices[0].message.content",
                        reason="bad_response", requested_model=m)
    # Response cũ/mock thiếu field → None, không được làm hỏng ca ok.
    served = data.get("model") if isinstance(data.get("model"), str) else None
    provider = data.get("provider") if isinstance(data.get("provider"), str) else None
    return ORResult(ok=True, text=text, served_model=served, provider=provider,
                    requested_model=m)
