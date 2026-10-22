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
try:
    from lib.model_policy import (
        GO_PROVIDER,
        GO_VENDORS,
        ModelPolicyViolation,
        SelectionSource,
    )
    from lib.vendor_config import resolve_vendor_model, load_vendor_config, ResolvedTarget
    from lib.vision import check_vision_gate, VisionBlockedError, VisionError
    from lib.go_data_gate import (
        DATA_CLASS_CODE_NOPII,
        GoDataGateBlocked,
        evaluate_go_data_gate,
    )
except ImportError:
    from bin.lib.model_policy import (
        GO_PROVIDER,
        GO_VENDORS,
        ModelPolicyViolation,
        SelectionSource,
    )
    from bin.lib.vendor_config import resolve_vendor_model, load_vendor_config, ResolvedTarget
    from bin.lib.vision import check_vision_gate, VisionBlockedError, VisionError
    from bin.lib.go_data_gate import (
        DATA_CLASS_CODE_NOPII,
        GoDataGateBlocked,
        evaluate_go_data_gate,
    )
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
    build_opencode_cmd,
    build_hermes_cmd,
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


# ---------------------------------------------------------------------------
# Sandbox confinement của Go adapters
# ---------------------------------------------------------------------------
# opencode/hermes không có confinement đã chứng minh. Lane unsandboxed CHỈ mở
# qua cổng dữ liệu (bin/lib/go_data_gate.py): caller khai báo tường minh
# data_class='code-nopii', không attachment/vision, pg-redact pass.
# Hằng số dưới đây KHÔNG còn là bypass — lật nó lên cũng không mở gì.
GO_SANDBOX_CONFINED = False


def _openrouter_scoped_model(model: str | None) -> str:
    """OpenRouter dùng namespace `org/model` — đó KHÔNG phải provider khác.

    Prefix `openrouter/` trước khi parse để `meta-llama/llama-3-8b-instruct`
    không bị hiểu nhầm thành provider `meta-llama` (giữ compatibility với các
    slug org/model đang chạy), nhưng policy contributor/free vẫn chặn TRƯỚC
    network vì parse nhìn thấy đúng toàn bộ selector.
    """
    if model is None:
        return "auto"
    m = str(model).strip()
    if not m or m.lower() == "auto":
        return "auto"
    if m.lower().startswith("openrouter/"):
        return m
    return f"openrouter/{m}"


def resolve_dispatch_target(
    vendor: str,
    model: str | None = "auto",
    provider: str | None = None,
    effort: str | None = None,
    profile: str | None = None,
    source: str | SelectionSource = "explicit",
    allow_unknown: bool = False,
    cfg: dict | None = None,
) -> ResolvedTarget:
    """Resolver CHUNG cho CLI (`bin/dispatch.py`) và library (`run_vendor`).

    Một nguồn quyết định duy nhất ⇒ CLI và library không thể lệch nhau về
    model/provider/effort/source. Hàm này THUẦN: không probe, không spawn,
    không network, không đọc key.

    Bất biến:
    - source GỐC (auto/default/failover) không bị hoá thành `explicit` sau khi
      resolve — chỉ `auto` + không profile được nâng thành AUTO, còn lại giữ
      nguyên giá trị caller truyền vào.
    - Gemini chưa có approved concrete default (config ghi CHUA_KIEM): giữ
      nguyên `auto` để vendor tự chọn, KHÔNG bịa slug (plan: không invent model).
    - OpenRouter: prefix `openrouter/` trước parse để giữ org/model compatibility;
      policy (:free, router unresolved, contributor) áp trước network.
    """
    v_clean = (vendor or "").strip().lower()
    # Chuẩn hoá enum/str về đúng một dạng: caller có thể truyền SelectionSource
    # từ module import khác (bin.lib vs lib) — không được để lộ "SelectionSource.X"
    # vào result JSON.
    eff_source = getattr(source, "value", source)
    model_is_auto = model is None or str(model).strip().lower() == "auto"

    # 1. Source gốc: auto + không profile ⇒ AUTO (không phải explicit)
    if model_is_auto and profile is None:
        if eff_source == "explicit":
            eff_source = SelectionSource.AUTO

    # 2. Gemini auto: chưa có approved concrete default ⇒ giữ literal 'auto'
    if v_clean == "gemini" and model_is_auto and not profile:
        src_txt = getattr(eff_source, "value", eff_source)
        return ResolvedTarget(
            vendor=v_clean,
            model="auto",
            provider=provider,
            effort=effort,
            profile=None,
            source=src_txt,
            selector=None,
            warnings=[
                "[polykit] gemini auto: vendor tự chọn model; PolyKit KHÔNG bịa slug mặc định "
                "(chưa có approved concrete default)."
            ],
        )

    # 3. OpenRouter: giữ namespace org/model, chỉ scope dưới openrouter/
    target = str(model).strip() if model is not None else "auto"
    if v_clean == "openrouter":
        target = _openrouter_scoped_model(target)

    return resolve_vendor_model(
        vendor=v_clean,
        model=target,
        provider=provider,
        effort=effort,
        profile=profile,
        source=eff_source,
        cfg=cfg,
        allow_unknown=allow_unknown,
    )



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


def _classify_completed(vendor: str, model: str, res, served_model: str | None = None,
                        prompt: str | None = None) -> DispatchResult:
    """M2: map kết quả subprocess → DispatchResult. returncode!=0 kèm dấu hiệu
    quota (402/insufficient credit/exhausted) → skipped/quota_capped, KHÔNG crash,
    KHÔNG coi là lỗi generic. Dùng chung cho codex/claude/grok."""
    stdout = res.stdout or ""
    # Chưa có verified metadata envelope thì không suy đoán served=model ở default.
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
        # Non-ok ⇒ KHÔNG có bằng chứng model đã phục vụ, kể cả khi caller lỡ
        # truyền vào slug đã yêu cầu. Chỉ nhánh exit 0 mới được mang served.
        return DispatchResult(status="skipped", vendor=vendor, model=model,
                              summary=f"{vendor} quota-capped (402/exhausted)",
                              warnings=warnings, stdout=stdout,
                              exit_code=res.returncode, reason="quota_capped",
                              served_model=None)
    return DispatchResult(status="error", vendor=vendor, model=model,
                          summary=f"{vendor} failed with exit code {res.returncode}",
                          warnings=warnings, stdout=stdout, exit_code=res.returncode,
                          served_model=None)

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
    effort: str | None = None,
    provider: str | None = None,
    profile: str | None = None,
    source: any = "explicit",
    attachments: list[str] | None = None,
    synthetic_vision: bool = False,
    allow_sensitive_vision: bool = False,
    sensitive_confirmation: any = None,
    is_retry: bool = False,
    is_failover: bool = False,
    allow_unknown: bool = False,
    data_class: str | None = None,
) -> DispatchResult:
    """Cổng dispatch công khai. `stream=True` = --stream-diagnose: chạy vendor ở
    chế độ stream để khi timeout còn đọc được vendor đã đi tới đâu (BUG-6).

    Vision (Lô 9): `attachments` + `synthetic_vision` + `allow_sensitive_vision`
    là cổng PII. Mặc định KHÔNG có attachment nào được chấp nhận: real/unknown
    bị chặn trước prompt/probe/spawn. Consent sensitive phải là
    `SingleTurnConfirmation` (không nhận cờ/string), và `is_retry`/`is_failover`
    KHÔNG kế thừa consent.

    Sandbox Go (Lô 11): KHÔNG có tham số `sandbox_verified`/bypass nào.
    opencode/hermes chỉ chạy unsandboxed khi caller khai báo tường minh
    `data_class='code-nopii'` và cổng dữ liệu qua (không attachment/vision,
    pg-redact check prompt pass nếu có checker). Thiếu cờ ⇒ vẫn
    `sandbox_unsupported` như trước.

    Hậu xử lý stream áp cho MỌI kết quả nên tách ra lớp mỏng này, không đổi
    hành vi khi stream=False (mọi thứ y như cũ)."""
    # BUG-15: cảnh báo sinh ra ở bước probe (vd auth chưa xác minh được nhưng
    # vẫn dispatch) phải sống sót tới result JSON — P4 cấm nuốt warning.
    probe_warnings: list[str] = []
    # Cảnh báo chính sách model (catalog advisory, gemini auto…) cũng phải
    # xuống result JSON, không chỉ nằm trong nội bộ resolver.
    policy_warnings: list[str] = []
    result = _run_vendor(
        vendor=vendor,
        prompt=prompt,
        model=model,
        timeout=timeout,
        fmt=fmt,
        workdir=workdir,
        sandbox=sandbox,
        runner=runner,
        detector=detector,
        stream=stream,
        probe_warnings=probe_warnings,
        policy_warnings=policy_warnings,
        effort=effort,
        provider=provider,
        profile=profile,
        source=source,
        attachments=attachments,
        synthetic_vision=synthetic_vision,
        allow_sensitive_vision=allow_sensitive_vision,
        sensitive_confirmation=sensitive_confirmation,
        is_retry=is_retry,
        is_failover=is_failover,
        allow_unknown=allow_unknown,
        data_class=data_class,
    )
    extra = [w for w in (policy_warnings + probe_warnings) if w]
    if extra:
        result.warnings = extra + [w for w in result.warnings if w not in extra]
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
    probe_warnings: list[str] | None = None,
    policy_warnings: list[str] | None = None,
    effort: str | None = None,
    provider: str | None = None,
    profile: str | None = None,
    source: any = "explicit",
    attachments: list[str] | None = None,
    synthetic_vision: bool = False,
    allow_sensitive_vision: bool = False,
    sensitive_confirmation: any = None,
    is_retry: bool = False,
    is_failover: bool = False,
    allow_unknown: bool = False,
    data_class: str | None = None,
) -> DispatchResult:
    if probe_warnings is None:
        probe_warnings = []
    if policy_warnings is None:
        policy_warnings = []
    probe = None
    go_optin = False
    # Bằng chứng runner của đường opt-in ĐÃ thực sự được gọi. Cổng dữ liệu qua
    # chưa đủ: builder kiểm lại cổng (có thể fail lần hai) và skip vendor có
    # thể xảy ra trước spawn. Chỉ có mặt trong list này mới được ghi
    # unsandboxed=true (finding vòng 2 F1/F3).
    go_spawned: list[bool] = []
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
            reason="guard_violation",
        )

    # 2. MODEL POLICY + RESOLVER — TRƯỚC probe/detector/spawn/network.
    #    Dùng CHUNG resolver với CLI (resolve_dispatch_target) nên hai entrypoint
    #    không thể quyết định khác nhau. Source gốc (auto/default/failover) được
    #    truyền nguyên vào policy: không biến thành explicit sau khi resolve.
    try:
        resolved_target = resolve_dispatch_target(
            vendor=vendor,
            model=model,
            provider=provider,
            effort=effort,
            profile=profile,
            source=source,
            allow_unknown=allow_unknown,
        )
    except ModelPolicyViolation as e:
        reason = getattr(e, "reason", None) or "policy_violation"
        return DispatchResult(
            status="blocked",
            vendor=vendor,
            model=model,
            summary=f"dispatch blocked: {e}",
            warnings=[
                str(e),
                f"[polykit] reason={reason}; requested={model!r} source={getattr(source, 'value', source)!r} "
                "— blocked trước probe/spawn/network.",
            ],
            reason=reason,
            exit_code=1,
            served_model=None,
        )
    except DispatchError as e:
        reason = getattr(e, "reason", None) or "guard_violation"
        return DispatchResult(
            status="blocked",
            vendor=vendor,
            model=model,
            summary=f"dispatch blocked: {e}",
            warnings=[str(e), f"[polykit] reason={reason}"],
            reason=reason,
            exit_code=1,
            served_model=None,
        )

    resolved_model = resolved_target.model
    resolved_provider = resolved_target.provider
    resolved_effort = resolved_target.effort
    resolved_source = resolved_target.source
    policy_warnings.extend(w for w in resolved_target.warnings if w)

    # 4. CỔNG DỮ LIỆU GO (opencode/hermes) — TRƯỚC vision gate/detector/probe/
    #    spawn/network. Lane unsandboxed chỉ mở khi caller khai báo tường minh
    #    data_class='code-nopii' (không có bool override), không attachment/
    #    vision, và pg-redact check prompt pass (nếu có checker trên máy).
    if vendor in GO_VENDORS:
        try:
            gate_warnings = evaluate_go_data_gate(
                data_class=data_class,
                prompt=prompt,
                attachments=attachments,
                synthetic_vision=synthetic_vision,
                allow_sensitive_vision=allow_sensitive_vision,
                sensitive_confirmation=sensitive_confirmation,
                vendor=vendor,
            )
        except GoDataGateBlocked as e:
            if e.reason == "sandbox_unsupported":
                return DispatchResult(
                    status="blocked",
                    vendor=vendor,
                    model=resolved_model,
                    summary=f"vendor {vendor} blocked: sandbox_unsupported (no data_class opt-in)",
                    warnings=[
                        f"Go adapter '{vendor}' chỉ được chạy unsandboxed khi khai báo "
                        f"tường minh --data-class {DATA_CLASS_CODE_NOPII} (code/dữ liệu "
                        f"không PII). Không có cờ ⇒ chặn (sandbox_unsupported, Plan mục 83).",
                        f"[polykit] reason=sandbox_unsupported; requested={resolved_model!r} "
                        f"provider={(resolved_provider or GO_PROVIDER)!r} effort={resolved_effort!r} "
                        f"source={resolved_source!r} — KHÔNG probe, KHÔNG spawn, KHÔNG network.",
                        f"[polykit] cờ hợp lệ duy nhất: --data-class {DATA_CLASS_CODE_NOPII}; "
                        f"không có tham số bool/evidence_sandbox nào để bật.",
                    ],
                    reason="sandbox_unsupported",
                    exit_code=1,
                    served_model=None,
                    data_class=data_class,
                )
            # Các nhánh chặn còn lại (attachment/vision, PII, checker lỗi).
            return DispatchResult(
                status="blocked",
                vendor=vendor,
                model=resolved_model,
                summary=f"vendor {vendor} blocked: {e.reason}",
                warnings=[
                    str(e),
                    f"[polykit] reason={e.reason}; unsandboxed=false; "
                    f"data_class={data_class!r} — KHÔNG probe, KHÔNG spawn, KHÔNG network.",
                ],
                reason=e.reason,
                exit_code=1,
                served_model=None,
                data_class=data_class,
            )
        # Cổng 1 qua (chưa spawn). Chỉ riêng cờ này KHÔNG đủ để ghi
        # unsandboxed=true: builder còn kiểm lại cổng (pg-redact có thể pass
        # rồi fail) và skip vendor có thể xảy ra trước spawn — xem `_mark_go`.
        go_optin = True
        policy_warnings.extend(gate_warnings)

    # 5. Vision Gate Check (TRƯỚC detector/probe/spawn/network!)
    if attachments:
        try:
            check_vision_gate(
                files=attachments,
                model=resolved_model,
                provider=resolved_provider or "",
                adapter=vendor,
                is_synthetic=synthetic_vision,
                allow_sensitive=allow_sensitive_vision,
                confirmation=sensitive_confirmation,
                is_retry=is_retry,
                is_failover=is_failover,
                workspace_root=workdir,
            )
        except VisionBlockedError as e:
            return DispatchResult(
                status="blocked",
                vendor=vendor,
                model=resolved_model,
                summary=f"vision gate blocked: {e}",
                warnings=[str(e)],
                reason="vision_blocked",
                exit_code=1,
                served_model=None,
            )
        except VisionError as e:
            return DispatchResult(
                status="blocked",
                vendor=vendor,
                model=resolved_model,
                summary=f"vision error: {e}",
                warnings=[str(e)],
                reason="vision_format_error",
                exit_code=1,
                served_model=None,
            )

    # 6. Probe detector
    # EXCEPTION: gemini có nhiều lane không phụ thuộc chỉ 1 binary
    if vendor != "gemini":
        cfg = load_vendor_config()
        if vendor not in REGISTRY and vendor not in cfg.get("vendors", {}):
            return DispatchResult(
                status="blocked",
                vendor=vendor,
                model=resolved_model,
                summary=f"unknown vendor: {vendor}",
                warnings=[],
                reason="unknown_vendor"
            )

        if vendor in REGISTRY:
            probe = detector(REGISTRY[vendor])
            state = classify(probe)
            if state == VendorState.AUTH_UNVERIFIED:
                # BUG-15 (23/08): auth_unverified nghĩa là polykit TỰ NHẬN không
                # biết — probe không authoritative và không có dấu hiệu mất auth.
                # Trước đây vẫn skip, mà người dùng chỉ đích danh vendor thì
                # không còn lane nào để degrade sang → mất trắng cả lượt dispatch
                # (prompt bay, stdout 0 byte) dù credential còn sống nguyên.
                # Thà nổ ở vendor với thông điệp thật, còn hơn skip với nhãn chỉ
                # SAI CHỖ (đúng tinh thần BUG-13).
                canh_bao = (f"auth chưa xác minh được cho {vendor} "
                            f"({probe.error or 'không rõ lý do'}) — vẫn dispatch, "
                            f"lỗi thật (nếu có) sẽ do vendor tự báo")
                probe_warnings.append(canh_bao)
                print(f"WARNING: {canh_bao}", file=sys.stderr)
            elif state != VendorState.READY:
                # BUG-15 req 4: kèm bằng chứng probe (thời gian/mã thoát) vào
                # thông điệp skip — nhãn trần không đủ để cãi lại.
                chi_tiet = f" — {probe.error}" if probe.error else ""
                # F3 (review vòng 2): caller ĐÃ khai data_class=code-nopii và
                # cổng đã qua, nên result JSON phải giữ dấu vết đó — nhưng
                # CHƯA spawn thì unsandboxed phải false (không tự nhận đã chạy
                # không sandbox) và warning phải nói rõ cổng qua / chưa spawn.
                skip_warnings: list[str] = []
                if go_optin:
                    skip_warnings.append(
                        f"[polykit] cổng data_class={DATA_CLASS_CODE_NOPII} đã qua "
                        f"nhưng vendor chưa sẵn sàng ({state.value}) — CHƯA spawn: "
                        f"unsandboxed=false, không có lượt chạy nào (served_model=null)."
                    )
                return DispatchResult(
                    status="skipped",
                    vendor=vendor,
                    model=resolved_model,
                    summary=f"vendor {vendor} skipped: {state.value}{chi_tiet}",
                    warnings=skip_warnings,
                    reason=state.value,
                    # Chưa spawn ⇒ KHÔNG có model nào đã phục vụ. `resolved_model`
                    # chỉ là Ý ĐỊNH (yêu cầu), không phải bằng chứng — ghi vào
                    # served_model là bịa (fallback Grok3: gpt-6.1-sol "served"
                    # trên một lượt skipped not_installed).
                    served_model=None,
                    unsandboxed=False,
                    data_class=DATA_CLASS_CODE_NOPII if go_optin else None,
                )

    # 7. env con
    env = os.environ.copy()
    env["XCLI_DISPATCH_DEPTH"] = str(depth + 1)

    # 8. Dispatch theo vendor
    def _mark_go(res: DispatchResult) -> DispatchResult:
        """Đường opt-in: result JSON phải nói rõ unsandboxed/data_class khi lượt
        chạy ĐÃ thực sự spawn (kể cả timeout/lỗi SAU cổng).

        `go_spawned` là bằng chứng runner đã được gọi. Cổng 1 qua mà builder
        kiểm lại cổng fail (vd pg-redact pass rồi fail), hoặc vendor bị skip
        trước spawn, thì KHÔNG ghi unsandboxed=true — blocked/skipped trước
        spawn không bao giờ tự nhận đã chạy không sandbox."""
        if go_optin and go_spawned:
            res.unsandboxed = True
            res.data_class = DATA_CLASS_CODE_NOPII
        return res

    def go_runner(*args, **kwargs):
        """Bọc runner để ghi bằng chứng spawn trước khi process có thể nổ."""
        go_spawned.append(True)
        return runner(*args, **kwargs)

    try:
        if vendor == "codex":
            cmd = build_codex_cmd(resolved_model, validated_sandbox, workdir, fmt, stream=stream, effort=resolved_effort, source=resolved_source)
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
            cmd = build_claude_cmd(resolved_model, prompt, source=resolved_source)
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
                cmd = build_grok_cmd(resolved_model, validated_sandbox, workdir, fmt, temp_prompt_path,
                                     stream=stream, source=resolved_source)
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
            # `auto` KHÔNG chọn catalog[0] hay phần tử đầu tiên khớp gemini-*:
            # catalog đổi mùa, chọn tùy tiện = đổi model ngoài quyết định của
            # người dùng. Chỉ dùng default ĐÃ DUYỆT; lệch catalog thì cảnh báo,
            # không tự đổi (plan: không invent model).
            resolved = resolved_model
            if resolved_model == "auto":
                resolved = AGY_DEFAULT_MODEL
            catalog = list(getattr(probe, "models", []) or [])
            if resolved == AGY_DEFAULT_MODEL and catalog and AGY_DEFAULT_MODEL not in catalog:
                policy_warnings.append(
                    f"[polykit] agy catalog live không chứa default đã duyệt "
                    f"{AGY_DEFAULT_MODEL!r}; vẫn gửi default đó, KHÔNG tự chọn model "
                    f"khác từ catalog."
                )
            cmd = build_agy_cmd(resolved, prompt, stream=stream,
                                timeout=validated_timeout, source=resolved_source)
            res = runner([shutil.which("agy") or "agy"] + cmd[1:],
                         capture_output=True, text=True,
                         timeout=validated_timeout, env=env)
            # CLI plaintext: LUÔN served=None, không tin stdout assistant JSON.
            out = _classify_completed(vendor, model, res, served_model=None, prompt=prompt)
            out.warnings.append(
                f"[polykit] agy không xác nhận model thực đã phục vụ "
                f"(chưa xác minh model thật); requested_model={resolved!r}."
            )
            return out

        elif vendor == "dsh":
            # dsh KHÔNG có cờ --model → viết file patch YAML rồi truyền --patch.
            # 🔴 auto → deepseek-v4-pro (KHÔNG phải flash — flash trả rỗng trên task nhiều bước).
            resolved = resolved_model
            if resolved_model == "auto":
                resolved = DSH_DEFAULT_MODEL

            # Tạo patch file tạm
            patch_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".yaml", delete=False, prefix="dsh-patch-"
                ) as pf:
                    patch_path = pf.name
                    write_dsh_patch(resolved, patch_path, source=resolved_source)

                cmd = build_dsh_cmd(resolved, patch_path, source=resolved_source)
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
                # CLI plaintext: LUÔN served=None, không tin stdout assistant JSON.
                out = _classify_completed(vendor, model, res, served_model=None, prompt=prompt)
                out.warnings.append(
                    f"[polykit] dsh không xác nhận model thực đã phục vụ "
                    f"(chưa xác minh model thật); requested_model={resolved!r}."
                )
                return out
            finally:
                if patch_path and os.path.exists(patch_path):
                    os.unlink(patch_path)

        elif vendor == "gemini":
            return _dispatch_gemini(prompt, resolved_model, validated_timeout, runner, env,
                                    stream=stream)

        elif vendor == "openrouter":
            from lib.openrouter import or_dispatch
            r = or_dispatch(
                prompt,
                model=resolved_model,
                timeout=validated_timeout,
                effort=resolved_effort,
                source=resolved_source,
                allow_unknown=allow_unknown,
            )
            if r.ok:
                summary = "openrouter completed successfully"
                if r.served_model and r.served_model != resolved_model:
                    summary += f" (served: {r.served_model})"
                return DispatchResult(status="ok", vendor=vendor, model=resolved_model,
                                      summary=summary,
                                      stdout=r.text, exit_code=0,
                                      served_model=r.served_model)
            if r.quota_capped:
                return DispatchResult(status="skipped", vendor=vendor, model=resolved_model,
                                      summary="openrouter quota-capped (402/429)",
                                      warnings=[r.error or ""], exit_code=r.http_code or 1,
                                      reason="quota_capped")
            r_reason = r.reason or "exec_error"
            is_blocked = (
                r_reason.endswith("_blocked")
                or "destination" in r_reason
                or r_reason in ("contributor_model_blocked", "free_model_not_explicit", "policy_violation")
            )
            return DispatchResult(
                status="blocked" if is_blocked else "error",
                vendor=vendor,
                model=resolved_model,
                summary=f"openrouter failed: {r.error}",
                warnings=[r.error or ""],
                exit_code=r.http_code or 1,
                reason=r_reason,
            )

        elif vendor in GO_VENDORS:
            # Nhánh RIÊNG cho Go adapters (opencode, hermes): argv list,
            # stdin=DEVNULL, cwd=workdir, effort truyền xuống builder.
            # Chỉ tới được đây khi cổng data_class=code-nopii đã qua (bước 4);
            # builder kiểm lại cổng + policy trước khi dựng argv.
            return _mark_go(_dispatch_go_adapter(
                vendor=vendor,
                prompt=prompt,
                model=resolved_model,
                effort=resolved_effort,
                attachments=attachments,
                sandbox=validated_sandbox,
                workdir=workdir,
                source=resolved_source,
                timeout=validated_timeout,
                env=env,
                runner=go_runner,
                data_class=data_class,
            ))

        else:
            # Handle dynamic vendors from JSON
            # Go adapters KHÔNG BAO GIỜ được rơi xuống fallback shell=True
            # (defensive: nhánh trên đã bắt, đây là chốt chống hồi quy).
            if vendor in GO_VENDORS:
                return DispatchResult(
                    status="blocked",
                    vendor=vendor,
                    model=resolved_model,
                    summary=f"vendor {vendor} blocked: sandbox_unsupported (no dynamic shell fallback)",
                    warnings=[
                        "Go adapters never fall back to the dynamic shell template "
                        "(no proven confinement)."
                    ],
                    reason="sandbox_unsupported",
                    exit_code=1,
                    served_model=None,
                )
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
            if resolved_model and resolved_model != "auto":
                if v_cfg.get("model_flag"):
                    cmd_has_model = True

            # served_model = model THẬT đã phục vụ, cần BẰNG CHỨNG (metadata
            # envelope do vendor trả). Dynamic CLI không có metadata đó: việc
            # argv có `--model <slug>` chỉ là Ý ĐỊNH của ta, không phải lời xác
            # nhận của vendor. ⇒ served LUÔN None; requested vẫn nằm ở `model`
            # và phải nói rõ vì sao (fallback Grok3: intent bị ghi thành served).
            served = None
            warning_msg = None
            if not cmd_has_model:
                warning_msg = f"vendor '{vendor}' không nhận cờ model, đang chạy mặc định của chính nó, không xác định được slug."
            else:
                warning_msg = (
                    f"vendor '{vendor}' nhận cờ model nhưng CLI không trả metadata xác thực "
                    f"model đã phục vụ: served_model=None; requested_model="
                    f"{resolved_model!r} chỉ là yêu cầu, chưa phải bằng chứng."
                )

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
                    model=resolved_model,
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
                    model=resolved_model,
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
                cmd += f" {v_cfg['model_flag']} {shlex.quote(resolved_model)}"
                    
            if workdir and v_cfg.get("workdir_flag"):
                cmd += f" {v_cfg['workdir_flag']} {shlex.quote(workdir)}"
                
            if validated_sandbox == "workspace-write" and v_cfg.get("auto_approve"):
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
            out = _classify_completed(vendor, resolved_model, res, served_model=served, prompt=prompt)
            return finalize(out)

    except subprocess.TimeoutExpired as e:
        # BUG-9: e mang theo e.stdout/e.stderr — phần vendor ĐÃ in ra trước khi
        # bị giết. Giữ lại vào stdout + warnings, thay vì vứt sạch manh mối.
        # Stream diagnose (BUG-6): với vendor stream, đọc thêm phần CHỮ trợ lý
        # trích từ JSONL — bằng chứng vendor đang NGHĨ, không treo.
        stdout = _decode_partial(e.stdout)
        stderr = _decode_partial(e.stderr)
        return _mark_go(DispatchResult(
            status="timeout",
            vendor=vendor,
            model=resolved_model,
            summary=f"{vendor} dispatch exceeded {validated_timeout}s",
            warnings=_stream_timeout_warnings(vendor, stdout, stderr, prompt, stream),
            # stdout để RỖNG có chủ ý: trường này là "kết quả vendor". Nhét output
            # dang dở vào đây thì caller chỉ kiểm `stdout != ""` sẽ đọc nửa vời
            # thành kết quả thật, và JSON phình không giới hạn (Codex review).
            # Phần dang dở đã nằm trong warnings, đã qua tail_lines.
            stdout="",
            reason="timeout",
        ))
    except Exception as e:
        return _mark_go(DispatchResult(
            status="error",
            vendor=vendor,
            model=resolved_model,
            summary=f"dispatch execution error: {str(e)}",
            warnings=[str(e)],
            reason="exec_error",
        ))

def _dispatch_go_adapter(
    vendor: str,
    prompt: str,
    model: str,
    effort: str | None,
    attachments: list[str] | None,
    sandbox: str,
    workdir: str | None,
    source: str,
    timeout: int,
    env: dict,
    runner,
    data_class: str | None = None,
) -> DispatchResult:
    """Nhánh RIÊNG cho Go adapters (opencode/hermes).

    Bất biến:
    - argv là LIST (không shell=True, không nội suy string) — prompt/Unicode
      nguyên vẹn, không bao giờ rơi xuống template dynamic.
    - stdin=DEVNULL (không đọc stdin của PolyKit), cwd=workdir, effort truyền
      xuống builder (variant của Go profile).
    - Builder kiểm lại cổng data_class=code-nopii; thiếu cờ ⇒ `blocked`
      reason sandbox_unsupported, không giả lập một lượt chạy đã xảy ra.
    - Mọi result ở đây mang unsandboxed/data_class của đường opt-in CHỈ SAU khi
      runner thật sự được gọi (kể cả lỗi sau cổng). Blocked trước spawn (builder
      từ chối cổng, argv hỏng) luôn unsandboxed=false.
    - Attachment đi vào cổng của CẢ HAI vendor: hermes không có cờ file, nhưng
      nhận attachment rồi lặng lẽ bỏ qua = mở lượt unsandboxed mà caller tưởng
      file đã được xét (review vòng 2 F2).
    """
    try:
        if vendor == "opencode":
            cmd = build_opencode_cmd(
                model=model,
                prompt=prompt,
                effort=effort,
                attachments=attachments,
                sandbox=sandbox,
                workdir=workdir,
                source=source,
                data_class=data_class,
            )
        else:
            cmd = build_hermes_cmd(
                model=model,
                prompt=prompt,
                effort=effort,
                attachments=attachments,
                sandbox=sandbox,
                workdir=workdir,
                source=source,
                data_class=data_class,
            )
    except DispatchError as e:
        reason = getattr(e, "reason", None) or "sandbox_unsupported"
        return DispatchResult(
            status="blocked",
            vendor=vendor,
            model=model,
            summary=f"vendor {vendor} blocked: {e}",
            warnings=[f"[polykit] reason={reason}; CHƯA spawn, unsandboxed=false.", str(e)],
            reason=reason,
            exit_code=1,
            served_model=None,
            # Builder từ chối = chưa có process nào chạy ⇒ không được nhận
            # unsandboxed chỉ vì caller đã khai data_class=code-nopii (F1).
            unsandboxed=False,
            data_class=data_class,
        )
    except Exception as e:  # noqa: BLE001 — builder lỗi bất ngờ vẫn là chưa spawn
        return DispatchResult(
            status="blocked",
            vendor=vendor,
            model=model,
            summary=f"vendor {vendor} blocked: builder error ({type(e).__name__})",
            warnings=[
                f"[polykit] reason=builder_error; CHƯA spawn, unsandboxed=false.",
                f"{type(e).__name__}: {e}",
            ],
            reason="builder_error",
            exit_code=1,
            served_model=None,
            unsandboxed=False,
            data_class=data_class,
        )

    if not isinstance(cmd, (list, tuple)) or not cmd:
        return DispatchResult(
            status="blocked",
            vendor=vendor,
            model=model,
            summary=f"vendor {vendor} blocked: Go adapter argv must be a non-empty list",
            warnings=["Go adapter argv is not a list — refusing to run (no shell fallback)."],
            reason="invalid_argv",
            exit_code=1,
            served_model=None,
            unsandboxed=False,
            data_class=data_class,
        )

    res = runner(
        list(cmd),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=workdir,
    )
    out = _classify_completed(vendor, model, res, served_model=None, prompt=prompt)
    if data_class == DATA_CLASS_CODE_NOPII:
        out.unsandboxed = True
        out.data_class = DATA_CLASS_CODE_NOPII
    return out


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
        or model.startswith("gemini-3.8-flash")
        or model.startswith("gemini-3.7-flash")
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
                # CLI plaintext: LUÔN served=None, không tin stdout assistant JSON.
                lane_warnings = list(warnings)
                lane_warnings.append(
                    f"[polykit] gemini lane 1 (agy) chưa xác minh model thật từ output; requested={model!r}."
                )
                return DispatchResult(
                    status="ok",
                    vendor="gemini",
                    model=model,
                    summary="gemini succeeded on lane 1 (agy)",
                    # `warnings=[]` cứng là cùng họ lỗi BUG-9(2): thành công KHÔNG
                    # có nghĩa là không có gì để nói. Cảnh báo "lane 1 không stream"
                    # bị nuốt sạch ở đây, để ghi chú chung nói hộ là đã stream.
                    warnings=lane_warnings,
                    stdout=res.stdout,
                    exit_code=0,
                    served_model=None,
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
        try:
            if model == "auto":
                # Grok finding 3: không bịa default gemini-3.5-flash khi model auto.
                cmd = [gemini_bin, "-p", prompt]
                if stream:
                    cmd = [gemini_bin, "-o", "stream-json", "-p", prompt]
            else:
                cmd = [gemini_bin, "-m", model, "-p", prompt]
                if stream:
                    cmd = [gemini_bin, "-m", model, "-o", "stream-json", "-p", prompt]
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
                # CLI plaintext: LUÔN served=None, không tin stdout assistant JSON.
                deg_warnings.append(
                    f"[polykit] gemini lane 2 (cli) chưa xác minh model thật từ output; requested={model!r}."
                )
                return DispatchResult(
                    status="ok",
                    vendor="gemini",
                    model=model,
                    summary="gemini succeeded on lane 2 (cli)",
                    warnings=deg_warnings,
                    stdout=res.stdout,
                    exit_code=0,
                    served_model=None,
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
                # Chỉ đọc actual metadata từ HTTP Gemini API top-level response.modelVersion (không đọc candidate text)
                raw_model = resp_data.get("modelVersion")
                proven_model = raw_model.strip() if (isinstance(raw_model, str) and raw_model.strip()) else None
                if proven_model is None:
                    deg_warnings.append(
                        f"[polykit] gemini lane 3 (api) chưa xác minh model thật từ API response; requested={model!r}."
                    )
                return DispatchResult(
                    status="ok",
                    vendor="gemini",
                    model=model,
                    summary="gemini succeeded on lane 3 (api)",
                    warnings=deg_warnings,
                    stdout=stdout,
                    exit_code=0,
                    served_model=proven_model,
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
