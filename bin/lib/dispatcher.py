from __future__ import annotations
import os
import sys
import shutil
import tempfile
import subprocess
import json
import urllib.request
import urllib.error
from pathlib import Path
from lib.states import classify, VendorState
from lib.vendors import detect, REGISTRY
from lib.quota_error import is_quota_error
from lib.dispatch_core import (
    DispatchError,
    DispatchResult,
    validate_timeout,
    validate_sandbox,
    build_codex_cmd,
    build_claude_cmd,
    build_grok_cmd,
    build_agy_cmd,
    build_dsh_cmd,
    write_dsh_patch,
    extract_stream_text,
    AGY_DEFAULT_MODEL,
    DSH_DEFAULT_MODEL,
    gemini_agy_tier,
)


STDERR_KEEP = 20
STDERR_HEAD = 3

# Vendor KHÔNG có chế độ stream (đo thật / theo README — xem BUG-6):
#   claude    — lane bị ràng buộc ToS, không đụng.
#   dsh       — `--profile headless` = "print the FINAL assistant message, and exit".
#   openrouter — HTTP API, không có CLI stream.
# ⚠️ `gemini` KHÔNG nằm ở đây vì lane 2 (gemini-cli) CÓ nhận `-o stream-json`.
#    Nhưng lane 1 (agy.sh wrapper) thì KHÔNG — nên khi lane 1 chạy phải nói rõ,
#    không được để ghi chú chung "output là JSONL stream" nói thay (Codex review).
# Khi --stream-diagnose gặp vendor này: cảnh báo RÕ rồi chạy bình thường,
# TUYỆT ĐỐI không im lặng bỏ qua, không giả vờ đã stream.
STREAM_UNSUPPORTED = frozenset({"claude", "dsh", "openrouter"})

_STREAM_UNSUPPORTED_REASON = {
    "claude": "lane bị ràng buộc ToS",
    "dsh": "--profile headless chỉ in kết quả CUỐI",
    "openrouter": "HTTP API, không có CLI stream",
}


def strip_echoed_prompt(stderr: str, prompt: str | None) -> str:
    """Bỏ đoạn stderr chính là PROMPT bị vendor echo lại.

    Đo thật 20/08/2026: `codex exec` in prompt ra stderr (dòng 13-14 của bản ghi
    mẫu). Nếu không bỏ, mọi phép dò trên stderr đều đọc luôn chữ của chính mình:
    một prompt chứa "hit your usage limit" (ví dụ đang nhờ review sổ bug —
    docs/BUGS.md có cụm đó 4 lần) sẽ bị xếp nhầm thành `quota_capped`, và
    failover đi sai nhánh đúng chiều ngược với thứ bản vá này muốn sửa.

    Chỉ bỏ khi các dòng prompt xuất hiện LIỀN KHỐI trong stderr — an toàn hơn
    xoá theo tập hợp, vốn có thể xoá nhầm một dòng lỗi trùng chữ với prompt.
    """
    if not prompt or not prompt.strip():
        return stderr
    p_lines = [l for l in prompt.splitlines() if l.strip()]
    if not p_lines:
        return stderr
    s_lines = stderr.splitlines()
    # So khớp BỎ QUA DÒNG TRỐNG ở cả hai phía: đo thật 20/08 cho thấy codex giữ
    # lại các dòng trống của prompt, nên so khớp liền-khối nguyên văn TRƯỢT và
    # phần echo vẫn lọt vào phép dò (live test bắt được, unit test thì không).
    idx = [i for i, l in enumerate(s_lines) if l.strip()]
    body = [s_lines[i] for i in idx]
    n = len(p_lines)
    for k in range(len(body) - n + 1):
        if body[k:k + n] == p_lines:
            lo, hi = idx[k], idx[k + n - 1]
            return "\n".join(s_lines[:lo] + s_lines[hi + 1:])
    return stderr


def tail_lines(stderr: str, keep: int = STDERR_KEEP, head: int = STDERR_HEAD) -> list[str]:
    """Giữ `head` dòng ĐẦU (banner: version/model/workdir — cần để tái lập ca) và
    `keep` dòng CUỐI (nơi lỗi nằm).

    BUG-5 (đo 20/08/2026): trước đây lấy `[:20]`. Codex in banner rồi echo lại
    prompt ra stderr, nên với prompt dài thì dòng ERROR thật bị đẩy ra ngoài cửa
    sổ — `--result-json` chỉ còn `exit_code=1` trơ, không phân biệt được hết
    quota với lỗi cờ.
    """
    lines = stderr.splitlines()
    if len(lines) <= keep + head:
        return lines
    bo = len(lines) - keep - head
    return lines[:head] + [f"[polykit] …bỏ {bo} dòng giữa của stderr, giữ {head} dòng đầu + {keep} dòng CUỐI (nơi lỗi nằm)"] + lines[-keep:]


def _decode_partial(data) -> str:
    """Chuyển e.stdout/e.stderr của TimeoutExpired thành str để tái dùng
    strip_echoed_prompt/tail_lines (cả hai chỉ nhận str).

    TimeoutExpired mang theo output đúng kiểu subprocess được gọi: text=True →
    str, text=False → bytes, hoặc None khi chưa bắt được gì. Gom cả ba về str,
    KHÔNG để AttributeError/TypeError nổ lúc cắt dòng.
    """
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    if isinstance(data, str):
        return data
    # Runner giả / API khác có thể đưa vào thứ không phải str — helper này hứa
    # "không nổ" thì phải giữ lời, kể cả với kiểu ngoài dự kiến (Codex review).
    return str(data)


def _tag_vendor_lines(lines: list[str], channel: str) -> list[str]:
    """Gắn nhãn nguồn cho từng dòng output vendor, nhưng GIỮ nguyên ghi chú
    `[polykit] …bỏ … dòng` mà tail_lines tự chèn khi phải cắt — dòng đó là của
    PolyKit, không được gắn nhãn `[vendor:*]`."""
    tagged = []
    for line in lines:
        if line.startswith("[polykit]"):
            tagged.append(line)
        else:
            tagged.append(f"[vendor:{channel}] {line}")
    return tagged


def _timeout_warnings(stdout: str, stderr: str, prompt: str | None) -> list[str]:
    """BUG-9: dựng warnings cho ca timeout — GIỮ manh mối vendor kịp in ra TRƯỚC
    khi bị giết, thay vì vứt sạch rồi trả về warnings=[].

    Phân biệt rõ từng dòng:
      - `[polykit] …`                      → ghi chú của PolyKit (đếm dòng,
                                             báo 'DANG DỞ' / 'không in gì').
      - `[vendor:stdout] …`/`[vendor:stderr] …` → output DANG DỞ của vendor.
    Echo prompt (vendor in lại chữ mình gửi) bị bỏ bằng strip_echoed_prompt —
    đó không phải manh mối. Số dòng đếm ở đây tính trên stderr ĐÃ strip.
    """
    stderr_goc = stderr
    stderr = strip_echoed_prompt(stderr, prompt)
    warnings: list[str] = []

    if stdout.strip():
        warnings.append(
            f"[polykit] vendor kịp in {len(stdout.splitlines())} dòng ra STDOUT "
            "trước khi bị giết — output DANG DỞ:"
        )
        warnings.extend(_tag_vendor_lines(tail_lines(stdout), "stdout"))
    else:
        warnings.append("[polykit] vendor KHÔNG kịp in gì ra stdout trước khi bị giết.")

    if stderr.strip():
        warnings.append(
            f"[polykit] vendor kịp in {len(stderr.splitlines())} dòng ra STDERR "
            "trước khi bị giết — output DANG DỞ:"
        )
        warnings.extend(_tag_vendor_lines(tail_lines(stderr), "stderr"))
    elif stderr_goc.strip():
        # Phân biệt "im lặng thật" với "chỉ echo lại prompt rồi bị bỏ" — hai ca
        # này dẫn tới hai hướng chẩn đoán khác hẳn nhau (Codex review).
        warnings.append("[polykit] stderr chỉ có phần echo lại prompt, không còn "
                        "manh mối nào sau khi bỏ echo.")
    else:
        warnings.append("[polykit] vendor KHÔNG kịp in gì ra stderr trước khi bị giết.")

    return warnings


def _stream_not_supported_warning(vendor: str) -> str:
    """Cảnh báo RÕ RÀNG rằng --stream-diagnose không áp dụng cho vendor này."""
    reason = _STREAM_UNSUPPORTED_REASON.get(vendor, "không có chế độ stream")
    return (
        f"[polykit] --stream-diagnose KHÔNG áp dụng cho vendor '{vendor}': "
        f"{reason}. Chạy bình thường, KHÔNG stream."
    )


def _stream_timeout_warnings(vendor: str, stdout: str, stderr: str,
                             prompt: str | None, stream: bool) -> list[str]:
    """Timeout ở chế độ stream: vẫn giữ manh mối như _timeout_warnings, NHƯNG
    thêm phần CHỮ trợ lý trích từ JSONL stream — chính là thứ BUG-6 đang cần để
    biết vendor đã nghĩ tới đâu (42 thought trong 4790 byte)."""
    warnings = _timeout_warnings(stdout, stderr, prompt)
    if stream and vendor not in STREAM_UNSUPPORTED:
        text = extract_stream_text(stdout)
        if text.strip():
            warnings.append(
                "[polykit] trích từ JSONL stream — chữ trợ lý/thought vendor đã kịp sinh:"
            )
            warnings.extend(_tag_vendor_lines(tail_lines(text), "stream"))
        else:
            warnings.append(
                "[polykit] không trích được chữ từ JSONL stream — output thô đã nằm ở trên."
            )
    return warnings


def _apply_stream_diagnose(result: DispatchResult, vendor: str, stream: bool,
                           fmt: str = "text") -> DispatchResult:
    """Hậu xử lý --stream-diagnose, chạy cho MỌI kết quả (ok/error/timeout/skipped).

    - Vendor KHÔNG stream → chèn cảnh báo rõ vào ĐẦU warnings, giữ nguyên mọi thứ.
    - Vendor CÓ stream → ghi chú chế độ chẩn đoán; nếu THÀNH CÔNG thì trích chữ
      trợ lý ra stdout (không trích được thì GIỮ NGUYÊN thô, không mất dữ liệu).
    """
    if not stream:
        return result
    if vendor in STREAM_UNSUPPORTED:
        result.warnings.insert(0, _stream_not_supported_warning(vendor))
        return result
    result.warnings.append(
        "[polykit] chế độ chẩn đoán (--stream-diagnose): output là JSONL stream; "
        "phần chữ trợ lý đã được trích (giữ nguyên thô nếu không trích được)."
    )
    if fmt == "json":
        # --stream-diagnose --format json: caller ĐANG CẦN JSON. Thay stdout bằng
        # chữ đã trích là phá hợp đồng output của chính họ (Codex review).
        result.warnings.append(
            "[polykit] --format json: giữ nguyên JSONL thô ở stdout, KHÔNG trích chữ."
        )
        return result
    if result.status == "ok" and result.stdout:
        text = extract_stream_text(result.stdout)
        if text.strip():
            result.stdout = text
    return result


def _classify_completed(vendor: str, model: str, res, served_model: str | None = False,
                        prompt: str | None = None) -> DispatchResult:
    """M2: map kết quả subprocess → DispatchResult. returncode!=0 kèm dấu hiệu
    quota (402/insufficient credit/exhausted) → skipped/quota_capped, KHÔNG crash,
    KHÔNG coi là lỗi generic. Dùng chung cho codex/claude/grok."""
    stdout = res.stdout or ""
    # `auto` = để CLI tự chọn → không suy ra được model thật, để None thay vì bịa.
    if served_model is False:
        served = None if model == "auto" else model
    else:
        served = served_model
    # Bỏ phần vendor echo lại prompt TRƯỚC khi dò lẫn khi hiển thị — nếu không,
    # PolyKit đọc chính chữ của mình rồi tưởng là lỗi của vendor.
    stderr = strip_echoed_prompt(res.stderr or "", prompt)

    if res.returncode == 0:
        # BUG-9(2): exit 0 KHÔNG có nghĩa là không có gì để nói. Vendor vẫn in
        # cảnh báo degraded / sắp hết quota / model thay thế ra stderr rồi thoát
        # sạch. Trước đây vứt hết, nên chỉ biết khi đã hỏng hẳn.
        return DispatchResult(status="ok", vendor=vendor, model=model,
                              summary=f"{vendor} completed successfully",
                              warnings=tail_lines(stderr) if stderr.strip() else [],
                              stdout=stdout, exit_code=0, served_model=served)

    # BUG-9(4): một số vendor ghi lỗi ra STDOUT (rõ nhất ở chế độ --json), khi đó
    # stderr rỗng và mọi phép dò trên stderr đều mù. Chỉ ngó sang stdout khi
    # stderr không có gì — để không nuốt nhầm kết quả thật thành "lỗi".
    # BUG-9(4): nhiều vendor ghi lỗi ra STDOUT (rõ nhất ở chế độ --json). Điều
    # kiện "chỉ ngó stdout khi stderr rỗng" KHÔNG đủ — live test 20/08 với
    # `codex --format json`: stderr có đúng một dòng vô dụng
    # ("Reading prompt from stdin...") nên guard không kích hoạt, còn lỗi thật
    # nằm trọn trong 944B stdout. ⇒ khi exit != 0 thì LUÔN kèm stdout làm nguồn
    # phụ, gắn nhãn rõ, và dò quota trên CẢ HAI.
    stdout_sach = strip_echoed_prompt(stdout, prompt)
    warnings = tail_lines(stderr) if stderr.strip() else []
    if stdout_sach.strip():
        warnings = warnings + ["[polykit] dấu vết thêm, lấy từ STDOUT:"] + tail_lines(stdout_sach)
    if not warnings:
        warnings = ["[polykit] vendor thoát với mã lỗi nhưng không in gì ra stdout lẫn stderr."]
    if is_quota_error(stderr + "\n" + stdout_sach, res.returncode):
        return DispatchResult(status="skipped", vendor=vendor, model=model,
                              summary=f"{vendor} quota-capped (402/exhausted)",
                              warnings=warnings, stdout=stdout,
                              exit_code=res.returncode, reason="quota_capped",
                              served_model=served)
    return DispatchResult(status="error", vendor=vendor, model=model,
                          summary=f"{vendor} failed with exit code {res.returncode}",
                          warnings=warnings, stdout=stdout, exit_code=res.returncode,
                          served_model=served)

def run_vendor(
    vendor: str,
    prompt: str,
    model: str = "auto",
    timeout: int = 120,
    fmt: str = "text",
    workdir: str | None = None,
    sandbox: str = "read-only",
    runner=subprocess.run,
    detector=detect,
    stream: bool = False,
) -> DispatchResult:
    """Cổng dispatch công khai. `stream=True` = --stream-diagnose: chạy vendor ở
    chế độ stream để khi timeout còn đọc được vendor đã đi tới đâu (BUG-6).

    Hậu xử lý stream áp cho MỌI kết quả nên tách ra lớp mỏng này, không đổi
    hành vi khi stream=False (mọi thứ y như cũ)."""
    result = _run_vendor(vendor, prompt, model, timeout, fmt, workdir, sandbox,
                         runner, detector, stream)
    return _apply_stream_diagnose(result, vendor, stream, fmt)


def _run_vendor(
    vendor: str,
    prompt: str,
    model: str = "auto",
    timeout: int = 120,
    fmt: str = "text",
    workdir: str | None = None,
    sandbox: str = "read-only",
    runner=subprocess.run,
    detector=detect,
    stream: bool = False,
) -> DispatchResult:
    # 1. Chạy guards
    try:
        validated_timeout = validate_timeout(timeout)
        validated_sandbox = validate_sandbox(sandbox)

        # Depth guard — non-int hoặc âm KHÔNG được bypass (Codex #1, #2).
        raw_depth = os.environ.get("XCLI_DISPATCH_DEPTH", "0")
        try:
            depth = int(raw_depth)
        except (ValueError, TypeError):
            raise DispatchError(f"XCLI_DISPATCH_DEPTH không phải số nguyên: {raw_depth!r}")
        if depth < 0:
            depth = 0  # clamp: âm không được lách qua ngưỡng >= 3
        if depth >= 3:
            raise DispatchError(f"depth {depth} >= 3, possible loop")
            
        # Prompt empty guard
        if not prompt or not prompt.strip():
            raise DispatchError("Empty prompt. Pipe content via stdin.")
            
    except DispatchError as e:
        return DispatchResult(
            status="blocked",
            vendor=vendor,
            model=model,
            summary=f"dispatch blocked: {str(e)}",
            warnings=[],
            reason="guard_violation"
        )

    # 2. Probe detector
    # EXCEPTION: gemini có nhiều lane không phụ thuộc chỉ 1 binary
    if vendor != "gemini":
        from lib.vendor_config import load_vendor_config
        cfg = load_vendor_config()
        if vendor not in REGISTRY and vendor not in cfg.get("vendors", {}):
            return DispatchResult(
                status="blocked",
                vendor=vendor,
                model=model,
                summary=f"unknown vendor: {vendor}",
                warnings=[],
                reason="unknown_vendor"
            )
        
        if vendor in REGISTRY:
            probe = detector(REGISTRY[vendor])
            state = classify(probe)
            if state != VendorState.READY:
                return DispatchResult(
                    status="skipped",
                    vendor=vendor,
                    model=model,
                    summary=f"vendor {vendor} skipped: {state.value}",
                    warnings=[],
                    reason=state.value,
                    served_model=None if model == "auto" else model
                )

    # 3. env con
    env = os.environ.copy()
    env["XCLI_DISPATCH_DEPTH"] = str(depth + 1)

    # 4. Dispatch theo vendor
    try:
        if vendor == "codex":
            cmd = build_codex_cmd(model, validated_sandbox, workdir, fmt, stream=stream)
            res = runner(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=validated_timeout,
                env=env,
            )
            return _classify_completed(vendor, model, res, prompt=prompt)

        elif vendor == "claude":
            cmd = build_claude_cmd(model, prompt)
            res = runner(
                cmd,
                capture_output=True,
                text=True,
                timeout=validated_timeout,
                env=env,
            )
            return _classify_completed(vendor, model, res, prompt=prompt)

        elif vendor == "grok":
            with tempfile.NamedTemporaryFile(mode="w+", delete=False) as temp_prompt:
                temp_prompt.write(prompt)
                temp_prompt_path = temp_prompt.name
            
            try:
                cmd = build_grok_cmd(model, validated_sandbox, workdir, fmt, temp_prompt_path,
                                     stream=stream)
                res = runner(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=validated_timeout,
                    env=env,
                )
                # M2: 402/insufficient-credit → quota_capped (không crash).
                return _classify_completed(vendor, model, res, prompt=prompt)
            finally:
                if os.path.exists(temp_prompt_path):
                    os.unlink(temp_prompt_path)

        elif vendor == "agy":
            # Codex review: `auto` mà ghim slug cứng thì catalog đổi mùa là gãy.
            # Ưu tiên chọn từ catalog LIVE vừa probe được; hết cách mới dùng hằng số.
            resolved = model
            if model == "auto":
                catalog = list(getattr(probe, "models", []) or [])
                if catalog:
                    resolved = (AGY_DEFAULT_MODEL if AGY_DEFAULT_MODEL in catalog
                                else next((m for m in catalog if m.startswith("gemini-")),
                                          catalog[0]))
            cmd = build_agy_cmd(resolved, prompt, stream=stream)
            res = runner([shutil.which("agy") or "agy"] + cmd[1:],
                         capture_output=True, text=True,
                         timeout=validated_timeout, env=env)
            out = _classify_completed(vendor, model, res, prompt=prompt)
            # served_model = slug ĐÃ GỬI. agy không báo lại model thật đã chạy,
            # nên đây là ý định, không phải bằng chứng (Grok P1) — ghi rõ để
            # đừng nhầm với served_model của OpenRouter (đọc từ response).
            # `resolved` chính là slug build_agy_cmd đã gửi (không phụ thuộc vị
            # trí cờ stream trong argv).
            out.served_model = resolved
            return out

        elif vendor == "dsh":
            # dsh KHÔNG có cờ --model → viết file patch YAML rồi truyền --patch.
            # 🔴 auto → deepseek-v4-pro (KHÔNG phải flash — flash trả rỗng trên task nhiều bước).
            resolved = model
            if model == "auto":
                resolved = DSH_DEFAULT_MODEL

            # Tạo patch file tạm
            patch_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".yaml", delete=False, prefix="dsh-patch-"
                ) as pf:
                    patch_path = pf.name
                    write_dsh_patch(resolved, patch_path)

                cmd = build_dsh_cmd(resolved, patch_path)
                # Append task prompt as positional arg
                cmd.append(prompt)

                # Inject DEEPSEEK_API_KEY from Keychain nếu chưa có trong env
                if "DEEPSEEK_API_KEY" not in env:
                    try:
                        key_res = subprocess.run(
                            ["security", "find-generic-password", "-a",
                             os.environ.get("USER", ""), "-s", "DEEPSEEK_API_KEY", "-w"],
                            capture_output=True, text=True, timeout=5,
                        )
                        if key_res.returncode == 0 and key_res.stdout.strip():
                            env["DEEPSEEK_API_KEY"] = key_res.stdout.strip()
                    except Exception:
                        pass  # best-effort

                res = runner(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=validated_timeout,
                    env=env,
                )
                out = _classify_completed(vendor, model, res, prompt=prompt)
                out.served_model = resolved
                return out
            finally:
                if patch_path and os.path.exists(patch_path):
                    os.unlink(patch_path)

        elif vendor == "gemini":
            return _dispatch_gemini(prompt, model, validated_timeout, runner, env,
                                    stream=stream)

        elif vendor == "openrouter":
            from lib.openrouter import or_dispatch
            r = or_dispatch(prompt, model=model, timeout=validated_timeout)
            if r.ok:
                # Router OR (auto/fusion/free) chọn model khác hẳn cái đã gọi —
                # ghi lại để biết tiền đi đâu (bench 03/08: fusion→opus-5 ~$1/lượt).
                summary = "openrouter completed successfully"
                if r.served_model and r.served_model != model:
                    summary += f" (served: {r.served_model})"
                return DispatchResult(status="ok", vendor=vendor, model=model,
                                      summary=summary,
                                      stdout=r.text, exit_code=0,
                                      served_model=r.served_model)
            if r.quota_capped:
                return DispatchResult(status="skipped", vendor=vendor, model=model,
                                      summary="openrouter quota-capped (402/429)",
                                      warnings=[r.error or ""], exit_code=r.http_code or 1,
                                      reason="quota_capped")
            return DispatchResult(status="error", vendor=vendor, model=model,
                                  summary=f"openrouter failed: {r.error}",
                                  warnings=[r.error or ""], exit_code=r.http_code or 1)

        else:
            # Handle dynamic vendors from JSON
            cfg = load_vendor_config()
            v_cfg = cfg.get("vendors", {}).get(vendor, {})
            if not v_cfg:
                return DispatchResult(
                    status="blocked",
                    vendor=vendor,
                    model=model,
                    summary=f"unknown vendor: {vendor}",
                    warnings=[],
                    reason="unknown_vendor"
                )
                
            cmd_has_model = False
            if model and model != "auto":
                if v_cfg.get("model_flag"):
                    cmd_has_model = True

            served = model if cmd_has_model else None
            warning_msg = None
            if not cmd_has_model:
                warning_msg = f"vendor '{vendor}' không nhận cờ model, đang chạy mặc định của chính nó, không xác định được slug."

            def finalize(result: DispatchResult) -> DispatchResult:
                if warning_msg:
                    if warning_msg not in result.warnings:
                        result.warnings.append(warning_msg)
                    sys.stderr.write(f"[polykit] warning: {warning_msg}\n")
                return result

            binary = v_cfg.get("binary")
            if binary and not shutil.which(binary):
                return finalize(DispatchResult(
                    status="skipped",
                    vendor=vendor,
                    model=model,
                    summary=f"vendor {vendor} skipped: not_installed",
                    warnings=[],
                    reason="not_installed",
                    served_model=served
                ))

            headless_tpl = v_cfg.get("headless")
            if not headless_tpl:
                return finalize(DispatchResult(
                    status="blocked",
                    vendor=vendor,
                    model=model,
                    summary=f"vendor {vendor} missing fields in JSON: headless",
                    warnings=[],
                    reason="missing_fields",
                    served_model=served
                ))
                
            import shlex
            cmd = headless_tpl
            input_data = None
            if "'<prompt>'" in cmd:
                cmd = cmd.replace("'<prompt>'", shlex.quote(prompt))
            elif '"<prompt>"' in cmd:
                cmd = cmd.replace('"<prompt>"', shlex.quote(prompt))
            elif "<prompt>" in cmd:
                cmd = cmd.replace("<prompt>", shlex.quote(prompt))
            elif "'<task>'" in cmd:
                cmd = cmd.replace("'<task>'", shlex.quote(prompt))
            elif '"<task>"' in cmd:
                cmd = cmd.replace('"<task>"', shlex.quote(prompt))
            elif "<task>" in cmd:
                cmd = cmd.replace("<task>", shlex.quote(prompt))
            else:
                input_data = prompt

            if cmd_has_model:
                cmd += f" {v_cfg['model_flag']} {shlex.quote(model)}"
                    
            if workdir and v_cfg.get("workdir_flag"):
                cmd += f" {v_cfg['workdir_flag']} {shlex.quote(workdir)}"
                
            if sandbox == "workspace-write" and v_cfg.get("auto_approve"):
                cmd += f" {v_cfg['auto_approve']}"

            res = runner(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=validated_timeout,
                env=env,
                input=input_data
            )
            out = _classify_completed(vendor, model, res, served_model=served, prompt=prompt)
            return finalize(out)

    except subprocess.TimeoutExpired as e:
        # BUG-9: e mang theo e.stdout/e.stderr — phần vendor ĐÃ in ra trước khi
        # bị giết. Giữ lại vào stdout + warnings, thay vì vứt sạch manh mối.
        # Stream diagnose (BUG-6): với vendor stream, đọc thêm phần CHỮ trợ lý
        # trích từ JSONL — bằng chứng vendor đang NGHĨ, không treo.
        stdout = _decode_partial(e.stdout)
        stderr = _decode_partial(e.stderr)
        return DispatchResult(
            status="timeout",
            vendor=vendor,
            model=model,
            summary=f"{vendor} dispatch exceeded {validated_timeout}s",
            warnings=_stream_timeout_warnings(vendor, stdout, stderr, prompt, stream),
            # stdout để RỖNG có chủ ý: trường này là "kết quả vendor". Nhét output
            # dang dở vào đây thì caller chỉ kiểm `stdout != ""` sẽ đọc nửa vời
            # thành kết quả thật, và JSON phình không giới hạn (Codex review).
            # Phần dang dở đã nằm trong warnings, đã qua tail_lines.
            stdout="",
            reason="timeout",
        )
    except Exception as e:
        return DispatchResult(
            status="error",
            vendor=vendor,
            model=model,
            summary=f"dispatch execution error: {str(e)}",
            warnings=[str(e)],
            reason="exec_error",
        )

def _dispatch_gemini(
    prompt: str,
    model: str,
    timeout: int,
    runner,
    env: dict,
    stream: bool = False,
) -> DispatchResult:
    # Strip 1 ký tự @ đầu prompt
    if prompt.startswith("@"):
        prompt = prompt[1:]

    warnings = []

    # --- Lane 1: agy ---
    agy_bin = shutil.which("agy.sh")
    if not agy_bin:
        home_agy = Path.home() / "scripts/agy.sh"
        if home_agy.is_file() and os.access(home_agy, os.X_OK):
            agy_bin = str(home_agy)

    is_agy_model = (
        model == "auto"
        or model.startswith("gemini-3.6-flash")
        or model.startswith("gemini-3.5-flash")
        or model.startswith("gemini-3.1-pro")
    )

    if is_agy_model and (agy_bin or shutil.which("agy")):
        if stream:
            # Lane 1 gọi wrapper agy.sh / `agy --print`, KHÔNG mang cờ stream.
            # Im lặng ở đây là để ghi chú chung nói hộ "đã stream" — đúng ca
            # GIẢ VỜ mà đề bài cấm (Codex review 20/08).
            warnings.append(
                "[polykit] --stream-diagnose: lane 1 (agy) KHÔNG nhận cờ stream — "
                "lượt này chạy plain. Chỉ lane 2 (gemini-cli) mới stream được."
            )
        tier = gemini_agy_tier(model)
        try:
            if agy_bin:
                cmd = [agy_bin, "-t", tier, prompt]
            else:
                cmd = ["agy", "--print", prompt]
                
            res = runner(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            if res.returncode == 0 and res.stdout and res.stdout.strip():
                # Slug thật do agy.sh quyết (tier→model), không hard-code lại ở đây
                # để khỏi lệch khi wrapper đổi — ghi lane+tier là thứ chắc chắn đúng.
                served = f"agy:{tier}" if agy_bin else "agy:default"
                return DispatchResult(
                    status="ok",
                    vendor="gemini",
                    model=model,
                    summary="gemini succeeded on lane 1 (agy)",
                    # `warnings=[]` cứng là cùng họ lỗi BUG-9(2): thành công KHÔNG
                    # có nghĩa là không có gì để nói. Cảnh báo "lane 1 không stream"
                    # bị nuốt sạch ở đây, để ghi chú chung nói hộ là đã stream.
                    warnings=list(warnings),
                    stdout=res.stdout,
                    exit_code=0,
                    served_model=served,
                )
            else:
                reason = "exit code nonzero" if res.returncode != 0 else "empty output"
                warnings.append(f"lane 1 failed: agy execution failed ({reason})")
                # BUG-9(3): lane gemini không đi qua _classify_completed, nên trước
                # đây stderr thật của vendor không bao giờ lộ ra — chỉ còn một dòng
                # "lane 1 failed" trơ, không đủ để biết nên sửa gì.
                _e = strip_echoed_prompt(res.stderr or "", prompt)
                if _e.strip():
                    warnings.extend(f"[lane 1:agy] {l}" for l in tail_lines(_e))
        except subprocess.TimeoutExpired as e:
            warnings.append("lane 1 failed: agy timed out")
            warnings.extend(_timeout_warnings(_decode_partial(e.stdout),
                                              _decode_partial(e.stderr), prompt))
        except Exception as e:
            warnings.append(f"lane 1 failed: {type(e).__name__}: {str(e)}")
    else:
        if not is_agy_model:
            warnings.append("lane 1 failed: model not supported by agy")
        else:
            warnings.append("lane 1 failed: agy.sh and agy unavailable")

    # --- Lane 2: gemini CLI ---
    gemini_bin = shutil.which("gemini")
    if gemini_bin:
        cli_model = "gemini-3.5-flash" if model == "auto" else model
        try:
            cmd = [gemini_bin, "-m", cli_model, "-p", prompt]
            if stream:
                # -o/--output-format stream-json là cờ stream của gemini CLI.
                cmd = [gemini_bin, "-m", cli_model, "-o", "stream-json", "-p", prompt]
            res = runner(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            if res.returncode == 0 and res.stdout and res.stdout.strip():
                deg_warnings = warnings.copy()
                deg_warnings.append("degraded: succeeded on lane 2")
                return DispatchResult(
                    status="ok",
                    vendor="gemini",
                    model=model,
                    summary="gemini succeeded on lane 2 (cli)",
                    warnings=deg_warnings,
                    stdout=res.stdout,
                    exit_code=0,
                    served_model=cli_model,
                )
            else:
                reason = "exit code nonzero" if res.returncode != 0 else "empty output"
                warnings.append(f"lane 2 failed: gemini-cli execution failed ({reason})")
                # BUG-9(3): lane gemini không đi qua _classify_completed, nên trước
                # đây stderr thật của vendor không bao giờ lộ ra — chỉ còn một dòng
                # "lane 2 failed" trơ, không đủ để biết nên sửa gì.
                _e = strip_echoed_prompt(res.stderr or "", prompt)
                if _e.strip():
                    warnings.extend(f"[lane 2:gemini-cli] {l}" for l in tail_lines(_e))
        except subprocess.TimeoutExpired as e:
            warnings.append("lane 2 failed: gemini-cli timed out")
            warnings.extend(_stream_timeout_warnings("gemini",
                                                     _decode_partial(e.stdout),
                                                     _decode_partial(e.stderr),
                                                     prompt, stream))
        except Exception as e:
            warnings.append(f"lane 2 failed: {type(e).__name__}: {str(e)}")
    else:
        warnings.append("lane 2 failed: gemini-cli unavailable")

    # --- Lane 3: API ---
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        key_file = Path.home() / ".gemini/api_key"
        if key_file.is_file():
            try:
                api_key = key_file.read_text().strip()
            except Exception as e:
                warnings.append(f"lane 3 failed: cannot read api_key file ({type(e).__name__}: {str(e)})")

    if api_key:
        api_model = "gemini-2.5-flash" if model == "auto" else model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{api_model}:generateContent"
        
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                
            parts = resp_data["candidates"][0]["content"]["parts"]
            stdout = "".join(p.get("text", "") for p in parts)
            
            if stdout and stdout.strip():
                deg_warnings = warnings.copy()
                deg_warnings.append("degraded: succeeded on lane 3")
                return DispatchResult(
                    status="ok",
                    vendor="gemini",
                    model=model,
                    summary="gemini succeeded on lane 3 (api)",
                    warnings=deg_warnings,
                    stdout=stdout,
                    exit_code=0,
                    served_model=api_model,
                )
            else:
                warnings.append("lane 3 failed: empty text response")
        except urllib.error.HTTPError as e:
            try:
                err_detail = e.read().decode("utf-8")
            except Exception:
                err_detail = str(e)
            warnings.append(f"lane 3 failed: HTTP error {e.code} ({err_detail})")
        except urllib.error.URLError as e:
            warnings.append(f"lane 3 failed: URL error ({str(e.reason)})")
        except Exception as e:
            warnings.append(f"lane 3 failed: API call failed ({type(e).__name__}: {str(e)})")
    else:
        warnings.append("lane 3 failed: API key unavailable")

    # All failed
    return DispatchResult(
        status="error",
        vendor="gemini",
        model=model,
        summary="all gemini lanes failed",
        warnings=warnings,
        stdout="",
        exit_code=1,
    )
