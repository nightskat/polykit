"""Model Policy and Selector Normalization for PolyKit.

Pure API for model policy enforcement, selector parsing, and safety guards.
Được thiết kế độc lập để các module sau (vendor_config, dispatch_core,
dispatcher, failover, watcher) import và sử dụng.

Quy tắc chính sách (P3, Plan 2026-10-22 mục 3 và mục 94):
1. Chặn cứng `*-contributor` vì có data training; không cho bypass kể cả allow_unknown.
2. Model `*-free` CHỈ được chọn tường minh (source='explicit'); cấm default/auto/failover.
   Caller tự dựng ModelSelector với is_free=False cũng không bypass được (tái parse/validate).
3. OpenRouter: Chặn cả router generic (`auto`, `free`, `free-router`, `:free`) LẪN model
   cụ thể gắn `:free` do chưa rõ chính sách riêng tư/lưu trữ/train (Plan mục 94).
4. Effective provider truyền riêng mâu thuẫn với selector.provider phải bị blocked.
5. Parser áp dụng grammar token chặt (ASCII slug [a-z0-9_.-]+), chặn shell, punctuation,
   Unicode homoglyphs, leading dash (-), path traversal (., ..), không normalize token sai.
6. Source lạ fail-closed (chỉ chấp nhận explicit, default, auto, failover).
7. Go adapter (opencode, hermes) chỉ chấp nhận provider 'opencode-go' và 2 profile paid đã duyệt:
   - deepseek-v4.1-flash với reasoning effort high
   - glm-5.3-flash với reasoning effort max
8. Model không có trong catalog (unknown) trên các vendor khác là advisory (warning),
   không whitelist cứng gây chặn oan model mới.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Enums & Constants
# ---------------------------------------------------------------------------

class SelectionSource(str, Enum):
    """Nguồn gốc của việc chọn model."""
    EXPLICIT = "explicit"    # Người dùng chọn qua cờ CLI (--model) hoặc API tường minh
    DEFAULT = "default"      # Lấy từ default_model trong config vendor
    AUTO = "auto"            # Cơ chế auto router
    FAILOVER = "failover"    # Đề xuất từ failover engine


# Danh sách nguồn hợp lệ (fail-closed cho bất kỳ nguồn nào ngoài nhóm này)
VALID_SOURCES = frozenset({s.value for s in SelectionSource})


class PolicyAction(str, Enum):
    """Quyết định kiểm tra policy."""
    ALLOW = "allow"          # Cho phép thực thi
    WARN = "warn"            # Cho phép thực thi kèm cảnh báo (advisory)
    BLOCK = "block"          # Chặn hoàn toàn


# Go adapter constants
GO_PROVIDER = "opencode-go"
GO_VENDORS = frozenset({"opencode", "hermes"})

GO_APPROVED_PROFILES: dict[str, str] = {
    "deepseek-v4.1-flash": "high",
    "glm-5.3-flash": "max",
}

DEFAULT_GO_PROFILE = ("deepseek-v4.1-flash", "high")

# Reasoning effort / variant hợp lệ (đồng bộ với dispatch_core.EFFORT_HOP_LE)
VALID_VARIANTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max"})

# OpenRouter generic routers (không có model đích cụ thể)
OPENROUTER_UNRESOLVED_TARGETS = frozenset({
    "auto",
    "free",
    "free-router",
    "router",
    ":free",
})

# Token grammar: ASCII slug [a-z0-9_.-]+, không rỗng
TOKEN_PATTERN = re.compile(r"^[a-z0-9_.-]+$")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ModelPolicyError(Exception):
    """Lỗi cơ sở cho toàn bộ model policy."""
    pass


class ModelPolicyViolation(ModelPolicyError):
    """Vi phạm chính sách model (contributor, free không tường minh, v.v.)."""
    def __init__(
        self,
        message: str,
        reason: str,
        model: str | None = None,
        provider: str | None = None,
    ):
        super().__init__(message)
        self.reason = reason
        self.model = model
        self.provider = provider


class MalformedSelectorError(ModelPolicyViolation):
    """Selector model sai cú pháp, ký tự không hợp lệ, hoặc mơ hồ."""
    def __init__(self, message: str, raw: str = ""):
        super().__init__(message, reason="malformed_selector", model=raw)


class ConflictingProviderError(MalformedSelectorError):
    """Provider truyền riêng mâu thuẫn với provider trong selector."""
    def __init__(self, message: str, raw: str = "", provider: str | None = None):
        super().__init__(message, raw=raw)
        self.reason = "conflicting_provider"
        self.provider = provider


class InvalidSourceError(ModelPolicyViolation):
    """Nguồn chọn model không hợp lệ / không nhận diện (fail-closed)."""
    def __init__(self, message: str, source: str | None = None, model: str | None = None):
        super().__init__(message, reason="invalid_source", model=model)
        self.source = source


class ContributorModelBlocked(ModelPolicyViolation):
    """Chặn cứng model contributor do rủi ro data training."""
    def __init__(
        self,
        message: str = "Contributor models are strictly forbidden (data training policy)",
        model: str | None = None,
    ):
        super().__init__(message, reason="contributor_model_blocked", model=model)


class FreeModelBlocked(ModelPolicyViolation):
    """Model free chỉ được chọn tường minh, không làm default/auto/failover."""
    def __init__(
        self,
        message: str = "Free models can only be selected explicitly (--model), not via default/auto/failover",
        model: str | None = None,
    ):
        super().__init__(message, reason="free_model_not_explicit", model=model)


class UnapprovedProviderError(ModelPolicyViolation):
    """Provider không được duyệt (Go adapter chỉ cho phép provider 'opencode-go')."""
    def __init__(
        self,
        message: str = "Go adapter only permits provider 'opencode-go'",
        provider: str | None = None,
    ):
        super().__init__(message, reason="unapproved_go_provider", provider=provider)


class UnresolvedDestinationError(ModelPolicyViolation):
    """OpenRouter router generic chưa rõ đích thực thi."""
    def __init__(
        self,
        message: str = "OpenRouter free/router models with unresolved destination are blocked",
        model: str | None = None,
    ):
        super().__init__(message, reason="openrouter_unresolved_destination", model=model)


class OpenRouterFreeBlocked(UnresolvedDestinationError):
    """OpenRouter model :free bị chặn do chưa rõ chính sách riêng tư/lưu trữ/train (plan 94)."""
    def __init__(
        self,
        message: str = "OpenRouter :free models are blocked due to unverified privacy/training policy (plan 94)",
        model: str | None = None,
    ):
        super().__init__(message, model=model)
        self.reason = "openrouter_free_blocked"


class UnapprovedProfileError(ModelPolicyViolation):
    """Profile không nằm trong danh mục đã duyệt của Go adapter."""
    def __init__(
        self,
        message: str,
        model: str | None = None,
    ):
        super().__init__(message, reason="unapproved_go_profile", model=model)


# ---------------------------------------------------------------------------
# Value Objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelSelector:
    """Value object biểu diễn selector model đã được chuẩn hoá."""
    raw: str
    provider: str | None = None
    model: str = ""
    variant: str | None = None
    is_free: bool = False
    is_contributor: bool = False
    is_router: bool = False

    def __post_init__(self) -> None:
        # Tự động tính lại flags an toàn, không tin cậy flags caller tự dựng truyền vào
        computed_free = is_free_model(self.model) or is_free_model(self.raw)
        computed_contrib = is_contributor_model(self.model) or is_contributor_model(self.raw)
        m_lower = self.model.strip().lower()
        computed_router = m_lower in OPENROUTER_UNRESOLVED_TARGETS

        if computed_free and not self.is_free:
            object.__setattr__(self, "is_free", True)
        if computed_contrib and not self.is_contributor:
            object.__setattr__(self, "is_contributor", True)
        if computed_router and not self.is_router:
            object.__setattr__(self, "is_router", True)

    @property
    def canonical_name(self) -> str:
        """Tên chuẩn provider/model nếu có provider, ngược lại model."""
        if self.provider:
            return f"{self.provider}/{self.model}"
        return self.model

    @property
    def full_target(self) -> str:
        """Tên chuẩn kèm variant nếu có."""
        if self.variant:
            return f"{self.canonical_name}:{self.variant}"
        return self.canonical_name


@dataclass(frozen=True)
class PolicyDecision:
    """Kết quả đánh giá chính sách đối với một model selector."""
    action: PolicyAction
    selector: ModelSelector
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def is_allowed(self) -> bool:
        return self.action in (PolicyAction.ALLOW, PolicyAction.WARN)

    @property
    def is_blocked(self) -> bool:
        return self.action == PolicyAction.BLOCK


# ---------------------------------------------------------------------------
# Classification & Validation Helpers
# ---------------------------------------------------------------------------

def validate_token(token: str, field_name: str = "Token") -> None:
    """Xác thực token theo grammar ASCII slug chặt: [a-z0-9_.-]+.

    Chặn:
    - Rỗng
    - Ký tự shell, punctuation khác ngoài [_ . -]
    - Ký tự non-ASCII / Unicode
    - Leading dash (-) hoặc trailing dash (-)
    - Path traversal (. hoặc ..) hoặc leading/trailing dot (.)
    """
    if not token:
        raise MalformedSelectorError(f"{field_name} cannot be empty")
    if not token.isascii():
        raise MalformedSelectorError(
            f"{field_name} contains non-ASCII or Unicode characters: {token!r}"
        )
    if token.startswith("-"):
        raise MalformedSelectorError(
            f"{field_name} cannot start with a dash (leading dash forbidden): {token!r}"
        )
    if token.endswith("-"):
        raise MalformedSelectorError(
            f"{field_name} cannot end with a dash: {token!r}"
        )
    if token in (".", "..") or token.startswith(".") or token.endswith("."):
        raise MalformedSelectorError(
            f"{field_name} cannot be path traversal or start/end with dot: {token!r}"
        )
    if not TOKEN_PATTERN.fullmatch(token):
        raise MalformedSelectorError(
            f"{field_name} contains invalid characters (must match ASCII slug [a-z0-9_.-]+): {token!r}"
        )


def is_contributor_model(name: str) -> bool:
    """Kiểm tra tên model/selector có chứa pattern contributor không."""
    if not name:
        return False
    lower = name.lower()
    return "contributor" in lower


def is_free_model(name: str) -> bool:
    """Kiểm tra model có thuộc diện free/khuyến mãi không."""
    if not name:
        return False
    lower = name.lower()
    if lower == "free" or lower.endswith("-free") or lower.endswith(":free"):
        return True
    if lower.startswith("free-") or lower.startswith("free/"):
        return True
    # Kiểm tra từng phần tách theo / hoặc :
    parts = re.split(r"[/:]", lower)
    if "free" in parts:
        return True
    if any(p.endswith("-free") for p in parts if p):
        return True
    return False


def is_openrouter_unresolved(selector: ModelSelector) -> bool:
    """Kiểm tra OpenRouter selector có phải là router generic chưa rõ model đích không."""
    is_or = (selector.provider == "openrouter") or (selector.raw.lower().startswith("openrouter/"))
    target = selector.model.lower()

    if target in OPENROUTER_UNRESOLVED_TARGETS:
        return True
    if is_or and (target in ("auto", "free", "free-router", "router", "") or target.endswith("/auto") or target.endswith("/free")):
        parts = target.split("/")
        if len(parts) == 1 and parts[0] in OPENROUTER_UNRESOLVED_TARGETS:
            return True
        if parts[-1] in ("free-router", "auto"):
            return True
        if parts[-1] == "free" and len(parts) == 1:
            return True
    return False


# ---------------------------------------------------------------------------
# Parser & Normalizer
# ---------------------------------------------------------------------------

def parse_model_selector(
    raw: str,
    default_provider: str | None = None,
    explicit_provider: str | None = None,
    explicit_variant: str | None = None,
    default_variant: str | None = None,
) -> ModelSelector:
    """Chuẩn hoá và phân tích cú pháp model selector theo grammar token chặt.

    Hỗ trợ các dạng:
    - Bare model: "deepseek-v4.1-flash"
    - Bare model kèm variant: "deepseek-v4.1-flash:high"
    - Provider/Model: "opencode-go/deepseek-v4.1-flash"
    - Provider/Model kèm variant: "opencode-go/deepseek-v4.1-flash:high"
    - OpenRouter scoped model: "openrouter/minimax/minimax-m3"
    - Khoảng trắng thừa quanh delimiter sẽ được strip tự động.

    Malformed / Ambiguous bị từ chối bằng MalformedSelectorError:
    - Rỗng, whitespace, ký tự điều khiển, non-ASCII Unicode
    - Delimiter rỗng: "a//b", "a::b", "/model", "model:", ":high"
    - Token sai grammar ASCII slug [a-z0-9_.-]+, leading dash, shell/punctuation
    - Mâu thuẫn giữa variant trong string và explicit_variant
    - Mâu thuẫn giữa provider trong string và explicit_provider
    - Khoảng trắng bên trong token (vd: "deep seek")
    """
    if not isinstance(raw, str):
        raise MalformedSelectorError(f"Model selector must be a string, got {type(raw).__name__}")

    if not raw.isascii():
        raise MalformedSelectorError(f"Model selector contains non-ASCII or Unicode characters: {raw!r}", raw=raw)

    s = raw.strip()
    if not s:
        raise MalformedSelectorError("Model selector cannot be empty", raw=raw)

    # Kiểm tra ký tự điều khiển
    if "\0" in s or any(ord(c) < 32 or ord(c) == 127 for c in s):
        raise MalformedSelectorError("Model selector contains control characters", raw=raw)

    # Kiểm tra delimiter kép
    if "//" in s or "::" in s:
        raise MalformedSelectorError(f"Model selector contains duplicate delimiters: {raw!r}", raw=raw)

    parsed_provider: str | None = None
    remaining = s

    if "/" in remaining:
        segments = remaining.split("/")
        for seg in segments:
            seg_s = seg.strip()
            if not seg_s:
                raise MalformedSelectorError(f"Malformed selector with empty segment: {raw!r}", raw=raw)

        if len(segments) == 2:
            parsed_provider = segments[0].strip().lower()
            remaining = segments[1].strip()
        elif len(segments) == 3 and segments[0].strip().lower() == "openrouter":
            parsed_provider = "openrouter"
            remaining = f"{segments[1].strip()}/{segments[2].strip()}"
        else:
            raise MalformedSelectorError(f"Ambiguous or malformed selector with multiple slashes: {raw!r}", raw=raw)
    else:
        # Không có slash, kiểm tra delimiter rỗng ở đầu/cuối
        pass

    # Xác thực token provider nếu có
    if parsed_provider:
        validate_token(parsed_provider, "Provider")

    # Giải quyết xung đột provider
    chosen_provider: str | None = None
    if parsed_provider:
        if explicit_provider:
            exp_p = explicit_provider.strip().lower()
            validate_token(exp_p, "Explicit provider")
            if parsed_provider != exp_p:
                raise ConflictingProviderError(
                    f"Conflicting provider: selector specifies {parsed_provider!r} but explicit provider is {exp_p!r}",
                    raw=raw,
                    provider=exp_p,
                )
        chosen_provider = parsed_provider
    else:
        cand_p = explicit_provider or default_provider
        if cand_p:
            chosen_provider = cand_p.strip().lower()
            validate_token(chosen_provider, "Provider")

    # Tách variant từ remaining nếu có dấu hai chấm ':'
    parsed_variant: str | None = None
    model_part = remaining.strip()

    if ":" in remaining:
        rem_clean = remaining.strip().lower()
        if rem_clean == ":free" and (parsed_provider == "openrouter" or (explicit_provider or default_provider) == "openrouter"):
            # Tag router đặc biệt của OpenRouter generic
            model_part = ":free"
        elif remaining.startswith(":") or remaining.endswith(":"):
            raise MalformedSelectorError(f"Malformed selector with empty colon segment: {raw!r}", raw=raw)
        else:
            colon_parts = [p.strip() for p in remaining.split(":")]
            if any(not p for p in colon_parts):
                raise MalformedSelectorError(f"Malformed selector with empty colon part: {raw!r}", raw=raw)

            if len(colon_parts) == 2:
                tag = colon_parts[1].lower()
                if tag in VALID_VARIANTS:
                    model_part = colon_parts[0]
                    parsed_variant = tag
                elif tag == "free":
                    model_part = f"{colon_parts[0]}:free"
                else:
                    raise MalformedSelectorError(
                        f"Invalid or unrecognized variant: {tag!r} (valid: {sorted(VALID_VARIANTS)})",
                        raw=raw,
                    )
            elif len(colon_parts) == 3 and colon_parts[1].lower() == "free":
                tag = colon_parts[2].lower()
                if tag in VALID_VARIANTS:
                    model_part = f"{colon_parts[0]}:free"
                    parsed_variant = tag
                else:
                    raise MalformedSelectorError(f"Invalid variant after :free: {tag!r}", raw=raw)
            else:
                raise MalformedSelectorError(f"Ambiguous colon usage in selector: {raw!r}", raw=raw)

    # Giải quyết xung đột variant
    final_variant: str | None = None
    if parsed_variant:
        if explicit_variant:
            exp_v = explicit_variant.strip().lower()
            if parsed_variant != exp_v:
                raise MalformedSelectorError(
                    f"Conflicting variant: selector specifies {parsed_variant!r} but explicit variant is {exp_v!r}",
                    raw=raw,
                )
        final_variant = parsed_variant
    else:
        cand_v = explicit_variant or default_variant
        if cand_v:
            cand_v = cand_v.strip().lower()
            if cand_v not in VALID_VARIANTS:
                raise MalformedSelectorError(
                    f"Invalid variant {cand_v!r} (valid: {sorted(VALID_VARIANTS)})",
                    raw=raw,
                )
            final_variant = cand_v

    # Chuẩn hoá model slug và xác thực từng token
    clean_model = model_part.strip().lower()
    if not clean_model:
        raise MalformedSelectorError("Model name cannot be empty", raw=raw)

    if clean_model != ":free":
        # Tách các subsegment theo slash
        for subseg in clean_model.split("/"):
            if subseg.endswith(":free"):
                base_token = subseg[:-5]
                validate_token(base_token, "Model")
            else:
                validate_token(subseg, "Model")

    # Phân tích đặc tính model
    free_flag = is_free_model(clean_model) or is_free_model(raw)
    contributor_flag = is_contributor_model(clean_model) or is_contributor_model(raw)
    router_flag = clean_model in OPENROUTER_UNRESOLVED_TARGETS

    return ModelSelector(
        raw=raw,
        provider=chosen_provider,
        model=clean_model,
        variant=final_variant,
        is_free=free_flag,
        is_contributor=contributor_flag,
        is_router=router_flag,
    )


# ---------------------------------------------------------------------------
# Profile Resolver
# ---------------------------------------------------------------------------

def resolve_go_profile(model: str, variant: str | None = None) -> tuple[str, str]:
    """Giải quyết model và variant cho Go adapter theo 2 profile đã duyệt.

    - deepseek-v4.1-flash -> variant mặc định 'high'
    - glm-5.3-flash -> variant mặc định 'max' (khi không ghi variant, lấy max từ hồ sơ)
    """
    clean_m = model.strip().lower()
    base_m = clean_m[:-5] if clean_m.endswith("-free") else clean_m

    if base_m in GO_APPROVED_PROFILES:
        approved_variant = GO_APPROVED_PROFILES[base_m]
        chosen_variant = variant or approved_variant
        return (clean_m, chosen_variant)

    raise UnapprovedProfileError(
        f"Model {model!r} is not an approved Go profile. Approved: {list(GO_APPROVED_PROFILES.keys())}",
        model=model,
    )


# ---------------------------------------------------------------------------
# Policy Verifier & Enforcer
# ---------------------------------------------------------------------------

def check_model_policy(
    selector: ModelSelector | str,
    vendor: str | None = None,
    provider: str | None = None,
    source: SelectionSource | str = SelectionSource.EXPLICIT,
    catalog_models: list[str] | set[str] | None = None,
    allow_unknown: bool = False,
) -> PolicyDecision:
    """Đánh giá model selector theo chính sách bảo mật và an toàn dữ liệu.

    Fail-closed:
    - Nguồn lạ (source không nằm trong SelectionSource) bị chặn ngay lập tức.
    - Value object ModelSelector được tái xác thực và tính toán lại mọi cờ,
      không tin cậy flags caller tự dựng.
    - Effective provider truyền riêng mâu thuẫn với selector.provider bị blocked.
    - OpenRouter generic router LẪN model cụ thể :free bị blocked (Plan mục 94).
    """
    # 0. CHỐT CHẶN NGUỒN: Source lạ fail-closed
    if isinstance(source, SelectionSource):
        norm_source = source.value
    elif isinstance(source, str):
        norm_source = source.strip().lower()
    else:
        norm_source = None

    if norm_source not in VALID_SOURCES:
        raw_val = selector.raw if isinstance(selector, ModelSelector) else str(selector)
        return PolicyDecision(
            action=PolicyAction.BLOCK,
            selector=selector if isinstance(selector, ModelSelector) else ModelSelector(raw=raw_val, model=raw_val),
            reason="invalid_source",
            warnings=[f"Unknown or invalid selection source: {source!r}. Must be one of {sorted(VALID_SOURCES)}."],
        )

    # 1. TÁI PARSE / VALIDATE VALUE OBJECT: Không tin cached flags
    if isinstance(selector, str):
        try:
            sel = parse_model_selector(selector, explicit_provider=provider)
        except MalformedSelectorError as e:
            return PolicyDecision(
                action=PolicyAction.BLOCK,
                selector=ModelSelector(raw=selector, model=selector),
                reason=e.reason,
                warnings=[str(e)],
            )
    elif isinstance(selector, ModelSelector):
        try:
            if not isinstance(selector.raw, str):
                raise MalformedSelectorError("ModelSelector raw must be a string")
            if not selector.raw.isascii():
                raise MalformedSelectorError(f"ModelSelector raw contains non-ASCII characters: {selector.raw!r}")
            if any(ord(c) < 32 or ord(c) == 127 for c in selector.raw):
                raise MalformedSelectorError("ModelSelector raw contains control characters")

            # Xác thực provider truyền riêng nếu có
            exp_provider = None
            if provider:
                exp_provider = provider.strip().lower()
                validate_token(exp_provider, "Explicit provider")

            # Xác thực selector.provider nếu có
            sel_provider = None
            if selector.provider:
                sel_provider = selector.provider.strip().lower()
                validate_token(sel_provider, "Selector provider")

            # Kiểm tra xung đột provider truyền riêng
            if exp_provider and sel_provider:
                if exp_provider != sel_provider:
                    return PolicyDecision(
                        action=PolicyAction.BLOCK,
                        selector=selector,
                        reason="conflicting_provider",
                        warnings=[
                            f"Conflicting provider: selector specifies {sel_provider!r} but explicit provider is {exp_provider!r}"
                        ],
                    )

            chosen_p = sel_provider or exp_provider

            if selector.variant:
                v_clean = selector.variant.strip().lower()
                if v_clean not in VALID_VARIANTS:
                    raise MalformedSelectorError(f"Invalid variant: {v_clean!r}")
            else:
                v_clean = None

            m_clean = selector.model.strip().lower()
            if not m_clean:
                raise MalformedSelectorError("Model name cannot be empty")
            if not m_clean.isascii():
                raise MalformedSelectorError(f"Model name contains non-ASCII characters: {m_clean!r}")

            if m_clean == ":free":
                effective_p = (chosen_p or "").lower()
                if effective_p != "openrouter" and not selector.raw.lower().startswith("openrouter/"):
                    raise MalformedSelectorError("Model selector ':free' is only valid with openrouter provider")
            else:
                for subseg in m_clean.split("/"):
                    if subseg.endswith(":free"):
                        validate_token(subseg[:-5], "Model")
                    else:
                        validate_token(subseg, "Model")

            # Tái tính toán cờ an toàn hoàn toàn từ dữ liệu thật, không tin cached flags
            recomputed_free = is_free_model(m_clean) or is_free_model(selector.raw)
            recomputed_contributor = is_contributor_model(m_clean) or is_contributor_model(selector.raw)
            recomputed_router = m_clean in OPENROUTER_UNRESOLVED_TARGETS

            sel = ModelSelector(
                raw=selector.raw,
                provider=chosen_p,
                model=m_clean,
                variant=v_clean,
                is_free=recomputed_free,
                is_contributor=recomputed_contributor,
                is_router=recomputed_router,
            )
        except MalformedSelectorError as e:
            return PolicyDecision(
                action=PolicyAction.BLOCK,
                selector=selector,
                reason=e.reason,
                warnings=[str(e)],
            )
    else:
        return PolicyDecision(
            action=PolicyAction.BLOCK,
            selector=ModelSelector(raw=str(selector), model=str(selector)),
            reason="malformed_selector",
            warnings=[f"Model selector must be a str or ModelSelector, got {type(selector).__name__}"],
        )

    # 2. CHỐT CHẶN CỨNG 1: Contributor LUÔN bị cấm (kể cả allow_unknown=True)
    if sel.is_contributor or is_contributor_model(sel.raw) or is_contributor_model(sel.model):
        return PolicyDecision(
            action=PolicyAction.BLOCK,
            selector=sel,
            reason="contributor_model_blocked",
            warnings=["Contributor models train on user data and are strictly forbidden."],
        )

    # 3. CHỐT CHẶN OPENROUTER: Router generic LẪN model cụ thể :free đều bị chặn (Plan mục 94)
    effective_provider = (sel.provider or provider or "").lower()
    is_openrouter = (effective_provider == "openrouter") or sel.raw.lower().startswith("openrouter/")
    if is_openrouter:
        if is_openrouter_unresolved(sel):
            return PolicyDecision(
                action=PolicyAction.BLOCK,
                selector=sel,
                reason="openrouter_unresolved_destination",
                warnings=[
                    f"OpenRouter selector {sel.canonical_name!r} has unresolved destination/routing. "
                    "Direct routing requires a concrete verified destination model."
                ],
            )
        if sel.is_free or is_free_model(sel.model) or is_free_model(sel.raw) or ":free" in sel.model:
            return PolicyDecision(
                action=PolicyAction.BLOCK,
                selector=sel,
                reason="openrouter_free_blocked",
                warnings=[
                    f"OpenRouter model {sel.canonical_name!r} with :free is blocked due to unverified "
                    "privacy, training, or retention policy (plan mục 94)."
                ],
            )

    # 4. CHỐT CHẶN CỨNG 2: Free model CHỈ cho phép khi chọn tường minh (source=explicit)
    if sel.is_free or is_free_model(sel.model) or is_free_model(sel.raw):
        if norm_source != SelectionSource.EXPLICIT.value:
            return PolicyDecision(
                action=PolicyAction.BLOCK,
                selector=sel,
                reason="free_model_not_explicit",
                warnings=[
                    f"Free model {sel.model!r} cannot be selected via {norm_source!r}. "
                    "Free models are limited to 200 req/day and must be chosen explicitly."
                ],
            )

    # 5. CHỐT CHẶN GO ADAPTER (opencode, hermes)
    is_go_vendor = vendor and (vendor.lower() in GO_VENDORS)
    is_go_provider = effective_provider == GO_PROVIDER

    if is_go_vendor or is_go_provider:
        # Quy tắc: Go chỉ chấp nhận provider 'opencode-go'
        if effective_provider and effective_provider != GO_PROVIDER:
            return PolicyDecision(
                action=PolicyAction.BLOCK,
                selector=sel,
                reason="unapproved_go_provider",
                warnings=[f"Go adapter only permits provider {GO_PROVIDER!r}, got {effective_provider!r}"],
            )

        # Kiểm tra profile Go:
        # Chỉ duyệt deepseek-v4.1-flash và glm-5.3-flash (hoặc phiên bản explicit -free của chúng)
        base_model = sel.model[:-5] if sel.model.endswith("-free") else sel.model
        if base_model not in GO_APPROVED_PROFILES:
            return PolicyDecision(
                action=PolicyAction.BLOCK,
                selector=sel,
                reason="unapproved_go_profile",
                warnings=[
                    f"Model {sel.model!r} is not an approved Go profile. "
                    f"Approved paid profiles: {sorted(GO_APPROVED_PROFILES.keys())}"
                ],
            )

        # Tự động gán variant nếu chưa có
        if not sel.variant:
            auto_variant = GO_APPROVED_PROFILES[base_model]
            sel = ModelSelector(
                raw=sel.raw,
                provider=GO_PROVIDER,
                model=sel.model,
                variant=auto_variant,
                is_free=sel.is_free,
                is_contributor=sel.is_contributor,
                is_router=sel.is_router,
            )

    # 6. CATALOG ADVISORY: Model catalog unknown hợp lệ là advisory, không whitelist cứng
    warnings: list[str] = []
    action = PolicyAction.ALLOW

    if catalog_models is not None:
        cat_set = {m.lower() for m in catalog_models}
        in_cat = (sel.model in cat_set) or (sel.canonical_name.lower() in cat_set)
        if not in_cat:
            action = PolicyAction.WARN
            warnings.append(
                f"Model {sel.canonical_name!r} is not present in the current verified catalog (advisory warning)."
            )

    return PolicyDecision(
        action=action,
        selector=sel,
        reason=None,
        warnings=warnings,
    )


def enforce_model_policy(
    selector: ModelSelector | str,
    vendor: str | None = None,
    provider: str | None = None,
    source: SelectionSource | str = SelectionSource.EXPLICIT,
    catalog_models: list[str] | set[str] | None = None,
    allow_unknown: bool = False,
) -> ModelSelector:
    """Thực thi chính sách model và ném exception nếu bị chặn.

    Trả về ModelSelector đã chuẩn hoá nếu hợp lệ (ALLOW hoặc WARN).
    Ném ModelPolicyViolation (hoặc subclass tương ứng) nếu vi phạm.
    """
    decision = check_model_policy(
        selector=selector,
        vendor=vendor,
        provider=provider,
        source=source,
        catalog_models=catalog_models,
        allow_unknown=allow_unknown,
    )

    if decision.is_blocked:
        reason = decision.reason or "policy_violation"
        msg = decision.warnings[0] if decision.warnings else f"Model policy blocked with reason: {reason}"
        raw_val = selector.raw if isinstance(selector, ModelSelector) else str(selector)

        if reason == "malformed_selector":
            raise MalformedSelectorError(msg, raw=raw_val)
        if reason == "conflicting_provider":
            raise ConflictingProviderError(msg, raw=raw_val, provider=provider)
        if reason == "invalid_source":
            raise InvalidSourceError(msg, source=str(source), model=decision.selector.model)
        if reason == "contributor_model_blocked":
            raise ContributorModelBlocked(msg, model=decision.selector.model)
        if reason == "free_model_not_explicit":
            raise FreeModelBlocked(msg, model=decision.selector.model)
        if reason == "unapproved_go_provider":
            raise UnapprovedProviderError(msg, provider=provider or decision.selector.provider)
        if reason == "openrouter_free_blocked":
            raise OpenRouterFreeBlocked(msg, model=decision.selector.model)
        if reason == "openrouter_unresolved_destination":
            raise UnresolvedDestinationError(msg, model=decision.selector.model)
        if reason == "unapproved_go_profile":
            raise UnapprovedProfileError(msg, model=decision.selector.model)

        raise ModelPolicyViolation(msg, reason=reason, model=decision.selector.model, provider=provider)

    return decision.selector
