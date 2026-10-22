from __future__ import annotations
import json
import os
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path

try:
    from lib.model_policy import (
        GO_APPROVED_PROFILES,
        GO_PROVIDER,
        GO_VENDORS,
        ConflictingProviderError,
        ContributorModelBlocked,
        FreeModelBlocked,
        MalformedSelectorError,
        ModelPolicyViolation,
        ModelSelector,
        PolicyAction,
        SelectionSource,
        UnapprovedProfileError,
        UnapprovedProviderError,
        check_model_policy,
        is_contributor_model,
        is_free_model,
        parse_model_selector,
    )
except ImportError:
    from bin.lib.model_policy import (
        GO_APPROVED_PROFILES,
        GO_PROVIDER,
        GO_VENDORS,
        ConflictingProviderError,
        ContributorModelBlocked,
        FreeModelBlocked,
        MalformedSelectorError,
        ModelPolicyViolation,
        ModelSelector,
        PolicyAction,
        SelectionSource,
        UnapprovedProfileError,
        UnapprovedProviderError,
        check_model_policy,
        is_contributor_model,
        is_free_model,
        parse_model_selector,
    )

try:
    from lib.vendor_config import resolve_vendor_model
except ImportError:
    from bin.lib.vendor_config import resolve_vendor_model

try:
    from lib.go_data_gate import (
        DATA_CLASS_CODE_NOPII,
        GoDataGateBlocked,
        evaluate_go_data_gate,
    )
except ImportError:
    from bin.lib.go_data_gate import (
        DATA_CLASS_CODE_NOPII,
        GoDataGateBlocked,
        evaluate_go_data_gate,
    )



class DispatchError(Exception):
    """Raised when dispatch guards or validation checks fail."""
    def __init__(
        self,
        message: str,
        reason: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ):
        super().__init__(message)
        self.reason = reason or "guard_violation"
        self.model = model
        self.provider = provider


class DispatchPolicyViolation(DispatchError, ModelPolicyViolation):
    """Vi phạm chính sách model trong tầng builder / dispatch."""
    def __init__(
        self,
        message: str,
        reason: str,
        model: str | None = None,
        provider: str | None = None,
    ):
        super().__init__(message=message, reason=reason, model=model, provider=provider)


class DispatchContributorBlocked(DispatchPolicyViolation, ContributorModelBlocked):
    """Chặn cứng model contributor ở builder do rủi ro data training."""
    def __init__(
        self,
        message: str = "Contributor models train on user data and are strictly forbidden.",
        model: str | None = None,
    ):
        super().__init__(message=message, reason="contributor_model_blocked", model=model)


class DispatchFreeBlocked(DispatchPolicyViolation, FreeModelBlocked):
    """Chặn model free không được chọn tường minh ở builder."""
    def __init__(
        self,
        message: str = "Free models can only be selected explicitly (--model), not via default/auto/failover",
        model: str | None = None,
    ):
        super().__init__(message=message, reason="free_model_not_explicit", model=model)


class DispatchUnapprovedProvider(DispatchPolicyViolation, UnapprovedProviderError):
    """Provider không được duyệt (Go adapter chỉ cho phép provider 'opencode-go')."""
    def __init__(
        self,
        message: str = "Go adapter only permits provider 'opencode-go'",
        provider: str | None = None,
    ):
        super().__init__(message=message, reason="unapproved_go_provider", provider=provider)


class DispatchUnapprovedProfile(DispatchPolicyViolation, UnapprovedProfileError):
    """Profile không nằm trong danh mục đã duyệt của Go adapter."""
    def __init__(
        self,
        message: str = "Unapproved Go profile",
        model: str | None = None,
    ):
        super().__init__(message=message, reason="unapproved_go_profile", model=model)


class DispatchMalformedSelector(DispatchPolicyViolation, MalformedSelectorError):
    """Selector model sai cú pháp hoặc mơ hồ."""
    def __init__(self, message: str, raw: str = ""):
        super().__init__(message=message, reason="malformed_selector", model=raw)


class DispatchConflictingProvider(DispatchPolicyViolation, ConflictingProviderError):
    """Provider truyền riêng mâu thuẫn với provider trong selector."""
    def __init__(self, message: str, raw: str = "", provider: str | None = None):
        super().__init__(message=message, reason="conflicting_provider", model=raw, provider=provider)


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
    # Lane Go unsandboxed (opencode/hermes): CHỈ true khi cổng data_class đã
    # qua (data_class == code-nopii + không attachment/vision + pg-redact pass).
    # Mọi đường blocked trước cổng đều để false — không tự nhận đã chạy.
    unsandboxed: bool = False
    data_class: str | None = None

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


# Bench 20/08/2026 (8 lượt, bài có đáp án kiểm được): trên gpt-5.6-terra,
# low = 366 reasoning tok → 3/5 lỗi · medium = 515 → 2/5 · high = 664 → 2/5.
# Effort cao ĐỐT NHIỀU HƠN mà tìm ÍT HƠN. codex mặc định chạy `medium` — đúng ô
# tệ nhất — nên PolyKit ghim `low`. `minimal` trả RỖNG, không bao giờ dùng.
CODEX_EFFORT_MAC_DINH = "low"
EFFORT_HOP_LE = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
CODEX_EFFORT_HOP_LE = EFFORT_HOP_LE

# Default models an toàn cho từng vendor khi gọi `auto`.
# Không dùng live catalog tùy ý để tránh drift/hỏng route an toàn (P1, Plan mục 3).
CODEX_DEFAULT_MODEL = "gpt-6.1-sol"
CLAUDE_DEFAULT_MODEL = "claude-opus-5"
GROK_DEFAULT_MODEL = "grok-4.6"
AGY_DEFAULT_MODEL = "gemini-3.8-flash-high"
DSH_DEFAULT_MODEL = "deepseek-v4-pro"
OPENCODE_DEFAULT_MODEL = "deepseek-v4.1-flash"
OPENCODE_DEFAULT_EFFORT = "high"
HERMES_DEFAULT_MODEL = "deepseek-v4.1-flash"
HERMES_DEFAULT_EFFORT = "high"

# Ghi chú lịch sử: KHÔNG còn là bypass. Lane Go unsandboxed chỉ mở qua cổng
# data_class=code-nopii (bin/lib/go_data_gate.py). Lật hằng số này không mở gì.
GO_SANDBOX_CONFINED: bool = False


def _enforce_builder_policy(
    vendor: str,
    model: str,
    provider: str | None = None,
    effort: str | None = None,
    source: str = "explicit",
) -> ModelSelector:
    """Kiểm tra và thực thi model policy fail-closed trước khi builder xây argv hoặc ghi file.

    - Nếu model là 'auto': resolve default model/effort qua resolver chung (vendor_config).
    - Chặn cứng mọi contributor model (kể cả explicit).
    - Chặn model free nếu source không phải explicit.
    - Go adapter (opencode, hermes) chỉ duyệt 2 profile paid (deepseek-v4.1-flash, glm-5.3-flash).
    - Model unknown hợp lệ trên vendor khác được giữ dạng advisory warning, không chặn oan.
    - Trả về ModelSelector đã chuẩn hoá (normalized model slug, variant/effort, provider).
    """
    v_clean = vendor.strip().lower()
    is_auto = (model.strip().lower() == "auto")

    if is_auto:
        # Resolver chung thay cho safe_defaults hardcoded
        try:
            resolved = resolve_vendor_model(
                vendor=v_clean,
                model="auto",
                effort=effort,
                source=SelectionSource.AUTO,
            )
        except ContributorModelBlocked as e:
            raise DispatchContributorBlocked(str(e), model=getattr(e, "model", None)) from e
        except FreeModelBlocked as e:
            raise DispatchFreeBlocked(str(e), model=getattr(e, "model", None)) from e
        except UnapprovedProviderError as e:
            raise DispatchUnapprovedProvider(str(e), provider=getattr(e, "provider", None)) from e
        except UnapprovedProfileError as e:
            raise DispatchUnapprovedProfile(str(e), model=getattr(e, "model", None)) from e
        except MalformedSelectorError as e:
            raise DispatchMalformedSelector(str(e), raw=getattr(e, "raw", "")) from e
        except ConflictingProviderError as e:
            raise DispatchConflictingProvider(str(e), raw=getattr(e, "raw", ""), provider=getattr(e, "provider", None)) from e
        except ModelPolicyViolation as e:
            raise DispatchPolicyViolation(str(e), reason=getattr(e, "reason", "policy_violation"), model=getattr(e, "model", None)) from e

        target_model = resolved.model
        effective_source = SelectionSource.AUTO
        effective_provider = resolved.provider
        effective_effort = effort or resolved.effort
    else:
        target_model = model
        effective_source = source
        effective_provider = provider
        effective_effort = effort
        if not effective_provider and v_clean in GO_VENDORS:
            # Nếu model chưa có provider prefix trong selector thì gán default GO_PROVIDER
            if "/" not in target_model:
                effective_provider = GO_PROVIDER

    try:
        sel = parse_model_selector(
            raw=target_model,
            default_provider=effective_provider,
            explicit_provider=effective_provider if provider else None,
            explicit_variant=effective_effort,
        )
    except MalformedSelectorError as e:
        raise DispatchMalformedSelector(str(e), raw=e.raw) from e
    except ConflictingProviderError as e:
        raise DispatchConflictingProvider(str(e), raw=e.raw, provider=provider) from e

    decision = check_model_policy(
        selector=sel,
        vendor=v_clean,
        provider=effective_provider,
        source=effective_source,
    )

    if decision.is_blocked:
        reason = decision.reason or "policy_violation"
        msg = decision.warnings[0] if decision.warnings else f"Model policy blocked with reason: {reason}"
        raw_val = decision.selector.raw if decision.selector else str(target_model)

        if reason == "contributor_model_blocked":
            raise DispatchContributorBlocked(msg, model=decision.selector.model)
        if reason == "free_model_not_explicit":
            raise DispatchFreeBlocked(msg, model=decision.selector.model)
        if reason == "unapproved_go_provider":
            raise DispatchUnapprovedProvider(msg, provider=effective_provider or (decision.selector.provider if decision.selector else None))
        if reason == "unapproved_go_profile":
            raise DispatchUnapprovedProfile(msg, model=decision.selector.model)
        if reason == "malformed_selector":
            raise DispatchMalformedSelector(msg, raw=raw_val)
        if reason == "conflicting_provider":
            raise DispatchConflictingProvider(msg, raw=raw_val, provider=effective_provider)

        raise DispatchPolicyViolation(msg, reason=reason, model=decision.selector.model, provider=effective_provider)

    return decision.selector


def build_codex_cmd(model: str, sandbox: str, workdir: str | None, fmt: str,
                    stream: bool = False, effort: str | None = None,
                    source: str = "explicit") -> list[str]:
    # Chốt chặn policy trước khi xây argv; auto resolve qua resolver chung
    selector = _enforce_builder_policy("codex", model, effort=effort, source=source)

    cmd = ["codex", "exec"]
    cmd.extend(["-m", selector.model])
    # codex KHÔNG có cờ --effort; chỉnh qua -c model_reasoning_effort=<mức>.
    muc = selector.variant or effort or CODEX_EFFORT_MAC_DINH
    if muc not in CODEX_EFFORT_HOP_LE:
        raise DispatchError(
            f"effort phải là một trong {', '.join(CODEX_EFFORT_HOP_LE)}, got: {muc!r}")
    cmd.extend(["-c", f"model_reasoning_effort={muc}"])
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


def build_claude_cmd(model: str, prompt: str, source: str = "explicit") -> list[str]:
    # Chốt chặn policy trước khi xây argv; auto resolve qua resolver chung
    selector = _enforce_builder_policy("claude", model, source=source)

    cmd = ["claude"]
    cmd.extend(["--model", selector.model])
    # Mandatory ToS-bounded options (P3) - không đổi effort Claude bounded
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
                   prompt_file: str, stream: bool = False, source: str = "explicit") -> list[str]:
    # Chốt chặn policy trước khi xây argv; auto resolve qua resolver chung
    selector = _enforce_builder_policy("grok", model, source=source)

    grok_bin = str(Path.home() / ".grok/bin/grok")
    cmd = [grok_bin, "--prompt-file", prompt_file]
    cmd.extend(["-m", selector.model])
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


def build_agy_cmd(model: str, prompt: str, stream: bool = False,
                  timeout: int | None = None, source: str = "explicit") -> list[str]:
    """Gọi THẲNG binary agy, không qua agy.sh — wrapper chỉ có 8 tier Gemini,
    trong khi agy còn phục vụ claude-*/gpt-oss-*.

    stream → --output-format stream-json (cờ TOÀN CỤC, phải đặt TRƯỚC lệnh con
    -p/--print — xem trap 'agy models --output-format json → exit 1').

    timeout → --print-timeout <N>s. BUG-17: agy mặc định cắt print mode ở 5m0s,
    KHÔNG theo --timeout của PolyKit. Đặt --timeout 600 mà không truyền cờ này
    thì agy tự chết ở 300s với "Error: timeout waiting for response", exit 1,
    stdout rỗng — mất trắng lượt trong khi PolyKit vẫn tưởng còn 5 phút nữa.
    Giá trị nhận Go duration; dùng giây cho khớp đơn vị --timeout."""
    # Chốt chặn policy trước khi xây argv; auto resolve qua resolver chung
    selector = _enforce_builder_policy("agy", model, source=source)

    cmd = ["agy"]
    if stream:
        cmd += ["--output-format", "stream-json"]
    if timeout:
        cmd += ["--print-timeout", f"{int(timeout)}s"]
    cmd += ["--model", selector.model, "-p", prompt]
    return cmd


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
    # 3.6 Flash — pinned via f36 tiers
    if model.startswith("gemini-3.6-flash"):
        if model.endswith("high"):
            return "f36-high"
        if model.endswith("low"):
            return "f36-low"
        return "f36"
    # 3.7 Flash — pinned via f37 tiers
    if model.startswith("gemini-3.7-flash"):
        if model.endswith("high"):
            return "f37-high"
        if model.endswith("low"):
            return "f37-low"
        return "f37"
    # 3.8 Flash (newest) + auto default + bare effort suffixes
    if model.endswith("low"):
        return "low"
    if model.endswith("med") or model.endswith("medium"):
        return "med"
    return "high"


def build_dsh_cmd(model: str, patch_file: str, source: str = "explicit") -> list[str]:
    """Tạo command line cho dsh.

    dsh KHÔNG có cờ --model. Phải viết file patch YAML rồi truyền --patch.
    patch_file do caller tạo (tempfile) với nội dung:
    - id: agent-default-model
      config: {provider: deepseek-official, model: <slug>}
    DSH auto phải pin patch command chứ không CLI auto, caller phải viết đúng modelpatch.
    """
    # Chốt chặn policy trước khi xây argv
    _enforce_builder_policy("dsh", model, source=source)

    cmd = ["dsh", "--profile", "headless"]
    cmd.extend(["--patch", patch_file])
    return cmd


def write_dsh_patch(model_slug: str, path: str, source: str = "explicit", effort: str | None = None) -> None:
    """Ghi file YAML patch cho dsh --patch. Chỉ dùng stdlib (yaml đơn giản).
    Chặn policy TRƯỚC KHI ghi file để không để lại artifacts vi phạm.
    """
    # Chốt chặn policy TRƯỚC KHI mở file hay ghi; auto resolve qua resolver chung
    selector = _enforce_builder_policy("dsh", model_slug, effort=effort, source=source)
    provider_name = selector.provider or "deepseek-official"

    content = (
        f"- id: agent-default-model\n"
        f"  config: {{provider: {provider_name}, model: {selector.model}}}\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Go Builders: OpenCode & Hermes
# ---------------------------------------------------------------------------

def get_opencode_bin() -> str:
    """Trả về đường dẫn tuyệt đối tới binary opencode: ~/.opencode/bin/opencode."""
    return str(Path.home() / ".opencode/bin/opencode")


def get_hermes_bin() -> str:
    """Trả về đường dẫn tuyệt đối tới binary hermes qua shutil.which."""
    which_b = shutil.which("hermes")
    if which_b:
        return str(Path(which_b).resolve())
    return "hermes"


def _build_opencode_argv(
    model: str,
    prompt: str,
    effort: str | None = None,
    attachments: list[str] | None = None,
    source: str = "explicit",
    data_class: str | None = None,
    synthetic_vision: bool = False,
    fmt: str = "text",
    workdir: str | None = None,
) -> list[str]:
    """Helper nội bộ xây dựng danh sách argv cho opencode run.

    KHÔNG gọi shell. Giữ prompt nguyên vẹn vị trí cuối (positional).
    -f dùng cho danh sách attachment (synthetic validation lô vision sau).
    `--` đứng ngay trước prompt để `-f` (array) không nuốt prompt thành file.
    fmt="json" ⇒ `--format json` (opencode phát raw JSON event stream, giữ được
    event tool_use để phát hiện nhiễm bẩn); fmt="text" giữ hành vi cũ.
    Dùng selector chuẩn hoá từ policy/resolver thay vì chuỗi thô.
    Lane unsandboxed chỉ mở khi caller khai báo data_class='code-nopii' và
    cổng dữ liệu (PII + attachment/vision) qua. Không có tham số bool override.
    """
    selector = _enforce_builder_policy(
        vendor="opencode",
        model=model,
        effort=effort,
        source=source,
    )

    try:
        evaluate_go_data_gate(
            data_class=data_class,
            prompt=prompt,
            attachments=attachments,
            synthetic_vision=synthetic_vision,
            vendor="opencode",
            model=selector.model,
            workdir=workdir,
        )
    except GoDataGateBlocked as e:
        raise DispatchError(
            str(e),
            reason=e.reason,
            model=selector.model,
            provider=selector.provider or GO_PROVIDER,
        ) from e

    # Xử lý attachment qua prepare_vision_input: DeepSeek tách trang PDF, GLM giữ PDF trực tiếp
    final_attachment_paths: list[str] = []
    if attachments:
        try:
            from lib.vision import prepare_vision_input, VisionError
        except ImportError:
            from bin.lib.vision import prepare_vision_input, VisionError
        try:
            prepared = prepare_vision_input(
                files=attachments,
                model=selector.model,
                provider=selector.provider or GO_PROVIDER,
                adapter="opencode",
                is_synthetic=synthetic_vision,
            )
            final_attachment_paths = [str(p) for p in prepared]
        except VisionError as e:
            raise DispatchError(
                str(e),
                reason="vision_blocked",
                model=selector.model,
                provider=selector.provider or GO_PROVIDER,
            ) from e
        except Exception as e:
            raise DispatchError(
                f"prepare_vision_input failed: {e}",
                reason="vision_blocked",
                model=selector.model,
                provider=selector.provider or GO_PROVIDER,
            ) from e

    bin_path = get_opencode_bin()
    norm_model = selector.model
    norm_effort = selector.variant or OPENCODE_DEFAULT_EFFORT
    provider_name = selector.provider or GO_PROVIDER

    cmd = [
        bin_path,
        "run",
        "--model",
        f"{provider_name}/{norm_model}",
        "--variant",
        norm_effort,
    ]
    if fmt == "json":
        # Raw JSON event stream: tool_use events survive for contamination checks.
        cmd.extend(["--format", "json"])
    if final_attachment_paths:
        for att in final_attachment_paths:
            cmd.extend(["-f", str(att)])
    # `-f/--file` là array (variadic) và `message` là positional array: không có
    # `--`, yargs nuốt prompt làm phần tử -f tiếp theo ⇒ vendor chết với
    # "File not found: <toàn prompt>". `--` chốt hết flag/file, prompt luôn
    # thành positional kể cả khi prompt bắt đầu bằng '-'.
    cmd.append("--")
    cmd.append(prompt)
    return cmd


def _build_hermes_argv(
    model: str,
    prompt: str,
    effort: str | None = None,
    source: str = "explicit",
    data_class: str | None = None,
    attachments: list[str] | None = None,
    synthetic_vision: bool = False,
) -> list[str]:
    """Helper nội bộ xây dựng danh sách argv cho hermes.

    KHÔNG gọi shell. Giữ prompt Unicode/quote/multiline nguyên vẹn sau cờ -z.
    Dùng selector chuẩn hoá từ policy/resolver thay vì chuỗi thô.
    Lane unsandboxed chỉ mở khi caller khai báo data_class='code-nopii' và
    cổng dữ liệu (PII + attachment/vision) qua. Không có tham số bool override.

    `attachments` PHẢI đi vào cổng: hermes không có cờ đính kèm, nhưng nuốt
    tham số này rồi vẫn dựng argv = lượt unsandboxed vẫn chạy trong khi caller
    tưởng file đã được xét. Có attachment (kể cả không tồn tại trên đĩa) ⇒
    `vision_blocked` trước checker/spawn.
    """
    selector = _enforce_builder_policy(
        vendor="hermes",
        model=model,
        effort=effort,
        source=source,
    )

    try:
        evaluate_go_data_gate(
            data_class=data_class,
            prompt=prompt,
            attachments=attachments,
            synthetic_vision=synthetic_vision,
            vendor="hermes",
        )
    except GoDataGateBlocked as e:
        raise DispatchError(
            str(e),
            reason=e.reason,
            model=selector.model,
            provider=selector.provider or GO_PROVIDER,
        ) from e

    bin_path = get_hermes_bin()
    norm_model = selector.model
    norm_effort = selector.variant or HERMES_DEFAULT_EFFORT
    provider_name = selector.provider or GO_PROVIDER

    cmd = [
        bin_path,
        "-z",
        prompt,
        "--provider",
        provider_name,
        "-m",
        norm_model,
        "--reasoning",
        norm_effort,
    ]
    return cmd


def build_opencode_cmd(
    model: str,
    prompt: str,
    effort: str | None = None,
    attachments: list[str] | None = None,
    sandbox: str = "read-only",
    workdir: str | None = None,
    source: str = "explicit",
    *,
    data_class: str | None = None,
    synthetic_vision: bool = False,
    fmt: str = "text",
) -> list[str]:
    """Builder cho OpenCode Go adapter.

    Chưa chứng minh sandbox cách ly trên adapter này. Chỉ mở unsandboxed khi
    caller khai báo tường minh data_class='code-nopii' (keyword-only) và cổng
    dữ liệu qua; thiếu cờ ⇒ DispatchError reason 'sandbox_unsupported'.
    Không có tham số bool nào bỏ được cổng.

    `fmt="json"` thêm `--format json` để giữ event stream thô (tool_use/…).
    `workdir` chỉ dùng làm cwd của tiến trình con, KHÔNG đổi trusted root của
    cổng vision (hằng số module).
    """
    validate_sandbox(sandbox)
    return _build_opencode_argv(
        model=model,
        prompt=prompt,
        effort=effort,
        attachments=attachments,
        source=source,
        data_class=data_class,
        synthetic_vision=synthetic_vision,
        fmt=fmt,
        workdir=workdir,
    )


def build_hermes_cmd(
    model: str,
    prompt: str,
    effort: str | None = None,
    sandbox: str = "read-only",
    workdir: str | None = None,
    source: str = "explicit",
    *,
    attachments: list[str] | None = None,
    data_class: str | None = None,
    synthetic_vision: bool = False,
) -> list[str]:
    """Builder cho Hermes Go adapter.

    Hermes oneshot tự bypass approval và vẫn tải tools/memory/rules, nên chỉ
    mở unsandboxed khi caller khai báo tường minh data_class='code-nopii'
    (keyword-only) và cổng dữ liệu qua; thiếu cờ ⇒ 'sandbox_unsupported'.
    Không có tham số bool nào bỏ được cổng.

    `attachments` là keyword-only và đi thẳng vào cổng dữ liệu: hermes không
    nhận cờ file, nên bỏ qua tham số này = chạy unsandboxed dù caller có nêu
    attachment. Có attachment ⇒ DispatchError reason 'vision_blocked'.
    """
    validate_sandbox(sandbox)
    return _build_hermes_argv(
        model=model,
        prompt=prompt,
        effort=effort,
        source=source,
        data_class=data_class,
        attachments=attachments,
        synthetic_vision=synthetic_vision,
    )



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
