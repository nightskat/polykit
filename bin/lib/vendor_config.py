"""Load and resolve vendor registry and model configuration from config/vendors.json.

Cung cấp:
- load_vendor_config(): đọc + cache file JSON, trả dict đầy đủ.
- vendor_names():       danh sách tên vendor (dùng cho argparse choices).
- default_model(name):  default_model của vendor, None nếu không có hoặc CHUA_KIEM.
- default_effort(name): default_effort của vendor.
- default_timeout(name): timeout mặc định riêng của vendor (BUG-18).
- vendor_traps(name):   list[str] traps, [] nếu không có.
- vendor_verify_cmd(name): verify_cmd string, None nếu không có.
- vendor_zero_quota_cmds(name): list[str] zero_quota_cmds.
- vendor_headless(name): headless command template.
- vendor_model_flag(name): model_flag string, None nếu không có.
- vendor_auth_hint(name): auth_hint string.
- vendor_provider(name): provider string nếu có (vd: opencode-go).
- vendor_quota_group(name): quota_group string nếu có (vd: opencode-go).
- vendor_profiles(name): dict các profiles được cấu hình cho vendor.
- vendor_zdr(name):     dict metadata ZDR nếu có.
- resolve_vendor_model() / resolve_model():
    Resolver chung model/provider/effort/profile/source dùng model_policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

try:
    from lib.model_policy import (
        GO_APPROVED_PROFILES,
        GO_PROVIDER,
        GO_VENDORS,
        ConflictingProviderError,
        ContributorModelBlocked,
        FreeModelBlocked,
        InvalidSourceError,
        MalformedSelectorError,
        ModelPolicyViolation,
        ModelSelector,
        OpenRouterFreeBlocked,
        PolicyAction,
        PolicyDecision,
        SelectionSource,
        UnapprovedProfileError,
        UnapprovedProviderError,
        UnresolvedDestinationError,
        check_model_policy,
        enforce_model_policy,
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
        InvalidSourceError,
        MalformedSelectorError,
        ModelPolicyViolation,
        ModelSelector,
        OpenRouterFreeBlocked,
        PolicyAction,
        PolicyDecision,
        SelectionSource,
        UnapprovedProfileError,
        UnapprovedProviderError,
        UnresolvedDestinationError,
        check_model_policy,
        enforce_model_policy,
        is_contributor_model,
        is_free_model,
        parse_model_selector,
    )

# config/ nằm cùng cấp bin/ trong repo
_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
_VENDORS_JSON = _CONFIG_DIR / "vendors.json"


@dataclass(frozen=True)
class ResolvedTarget:
    """Kết quả giải quyết cấu hình model cho một vendor."""
    vendor: str
    model: str
    provider: str | None = None
    effort: str | None = None
    profile: str | None = None
    source: str = "explicit"
    selector: ModelSelector | None = None
    warnings: list[str] = field(default_factory=list)
    quota_group: str | None = None
    zdr: dict | None = None

    @property
    def canonical_name(self) -> str:
        if self.selector:
            return self.selector.canonical_name
        if self.provider:
            return f"{self.provider}/{self.model}"
        return self.model

    @property
    def full_target(self) -> str:
        if self.selector:
            return self.selector.full_target
        cn = self.canonical_name
        if self.effort:
            return f"{cn}:{self.effort}"
        return cn


ResolvedModel = ResolvedTarget


@lru_cache(maxsize=1)
def load_vendor_config(path: Path | None = None) -> dict:
    """Đọc vendors.json, trả về dict gốc. Cache sau lần đầu."""
    p = path or _VENDORS_JSON
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("schema_version") != 3:
        raise ValueError(f"vendors.json schema_version != 3 (got {data.get('schema_version')})")
    for vendor_name, vendor_data in data.get("vendors", {}).items():
        if "models" in vendor_data:
            models_val = vendor_data["models"]
            if models_val is not None and not isinstance(models_val, list):
                raise ValueError(f"vendor '{vendor_name}' có trường 'models' sai dạng: {type(models_val).__name__}")
    return data


def vendor_names(cfg: dict | None = None) -> list[str]:
    """Danh sách tên vendor, giữ nguyên thứ tự trong JSON."""
    if cfg is None:
        cfg = load_vendor_config()
    return list(cfg.get("vendors", {}).keys())


def default_model(name: str, cfg: dict | None = None) -> str | None:
    """default_model của vendor. None nếu vendor không có trường này hoặc CHUA_KIEM."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    dm = vendor.get("default_model")
    if dm and dm != "CHUA_KIEM":
        return dm
    return None


def default_effort(name: str, cfg: dict | None = None) -> str | None:
    """default_effort của vendor. None nếu không có."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("default_effort") or vendor.get("effort_default_polykit")


def default_timeout(name: str, cfg: dict | None = None, fallback: int = 120) -> int:
    """Timeout mặc định RIÊNG của vendor (BUG-18)."""
    if cfg is None:
        cfg = load_vendor_config()
    vendors = cfg.get("vendors") if isinstance(cfg, dict) else None
    vendor = vendors.get(name) if isinstance(vendors, dict) else None
    val = vendor.get("default_timeout") if isinstance(vendor, dict) else None
    return val if type(val) is int and 1 <= val <= 600 else fallback


def vendor_traps(name: str, cfg: dict | None = None) -> list[str]:
    """Danh sách traps của vendor. [] nếu không có."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("traps", [])


def vendor_verify_cmd(name: str, cfg: dict | None = None) -> str | None:
    """verify_cmd string của vendor."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("verify_cmd")


def vendor_zero_quota_cmds(name: str, cfg: dict | None = None) -> list[str]:
    """zero_quota_cmds list."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("zero_quota_cmds", [])


def vendor_headless(name: str, cfg: dict | None = None) -> str | None:
    """headless command template."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("headless")


def vendor_model_flag(name: str, cfg: dict | None = None) -> str | None:
    """model_flag — None nếu vendor không có cờ --model."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("model_flag")


def vendor_auth_hint(name: str, cfg: dict | None = None) -> str | None:
    """auth_hint string."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("auth_hint")


def vendor_provider(name: str, cfg: dict | None = None) -> str | None:
    """provider string cấu hình cho vendor (vd: opencode-go)."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("provider")


def vendor_quota_group(name: str, cfg: dict | None = None) -> str | None:
    """quota_group string cấu hình cho vendor."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("quota_group")


def vendor_profiles(name: str, cfg: dict | None = None) -> dict[str, Any]:
    """Danh mục hồ sơ (profiles) của vendor. {} nếu không có."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return dict(vendor.get("profiles", {}) or {})


def vendor_zdr(name: str, cfg: dict | None = None) -> dict[str, Any] | None:
    """Metadata ZDR (Zero Data Retention) của vendor nếu có."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("zdr")


def resolve_vendor_model(
    vendor: str,
    model: str | None = None,
    provider: str | None = None,
    effort: str | None = None,
    profile: str | None = None,
    source: SelectionSource | str | None = None,
    cfg: dict | None = None,
    catalog_models: list[str] | set[str] | None = None,
    allow_unknown: bool = False,
) -> ResolvedTarget:
    """Resolver chung model/provider/effort/profile/source cho vendor.

    Tuân thủ các chốt chặn chính sách:
    1. Fail-closed khi default_model trong config chứa model free hoặc contributor.
    2. Alias/Profile không được biến lựa chọn gián tiếp thành explicit đối với model free.
    3. Contributor model cấm tuyệt đối ở mọi nguồn và cấu hình.
    4. allow_unknown=True KHÔNG bypass contributor, free, profile Go chưa duyệt, hay provider conflict.
    5. Xung đột giữa profile và model, hoặc provider/effort trong selector phải bị chặn.
    """
    v_clean = (vendor or "").strip().lower()
    if not v_clean:
        raise MalformedSelectorError("Vendor name cannot be empty")

    if cfg is None:
        cfg = load_vendor_config()

    vendors_dict = cfg.get("vendors", {}) if isinstance(cfg, dict) else {}
    vendor_info = vendors_dict.get(v_clean, {}) if isinstance(vendors_dict, dict) else {}

    cfg_default_model = vendor_info.get("default_model")
    if cfg_default_model == "CHUA_KIEM":
        cfg_default_model = None

    cfg_default_effort = vendor_info.get("default_effort") or vendor_info.get("effort_default_polykit")
    cfg_provider = vendor_info.get("provider")
    cfg_quota_group = vendor_info.get("quota_group")
    cfg_profiles = dict(vendor_info.get("profiles", {}) or {})
    cfg_zdr = vendor_info.get("zdr")

    resolved_profile_name: str | None = None
    target_model: str | None = None
    target_effort: str | None = None
    is_profile_resolution: bool = False
    is_default_resolution: bool = False

    # 1. Resolve Profile / Alias / Default / Explicit model
    if profile is not None:
        p_clean = profile.strip()
        if not p_clean:
            raise MalformedSelectorError("Profile name cannot be empty")

        matched_prof = None
        for k, v in cfg_profiles.items():
            if k.lower() == p_clean.lower():
                matched_prof = (k, v)
                break

        if matched_prof:
            prof_k, prof_v = matched_prof
            if isinstance(prof_v, str):
                target_model = prof_v
                target_effort = None
            elif isinstance(prof_v, dict):
                target_model = prof_v.get("model")
                target_effort = prof_v.get("effort")
            else:
                raise ModelPolicyViolation(f"Invalid profile configuration for {prof_k!r}")
            resolved_profile_name = prof_k
            is_profile_resolution = True
        else:
            p_lower = p_clean.lower()
            if v_clean in GO_VENDORS and p_lower in GO_APPROVED_PROFILES:
                target_model = p_lower
                target_effort = GO_APPROVED_PROFILES[p_lower]
                resolved_profile_name = p_lower
                is_profile_resolution = True
            else:
                raise UnapprovedProfileError(
                    f"Profile {profile!r} is not recognized or approved for vendor {vendor!r}",
                    model=profile,
                )

        # Kiểm tra xung đột giữa profile và model chỉ định cùng lúc
        if model is not None and model.strip().lower() != "auto":
            clean_m = model.strip().lower()
            m_base = clean_m.split(":")[0].split("/")[-1].strip()
            p_base = target_model.split(":")[0].split("/")[-1].strip().lower() if target_model else ""
            if m_base != p_base and clean_m != p_clean.lower():
                raise ModelPolicyViolation(
                    f"Conflicting profile and model: profile {profile!r} resolves to {target_model!r} but requested model is {model!r}",
                    reason="conflicting_profile",
                )

    elif model is not None and model.strip().lower() != "auto":
        clean_m = model.strip().lower()
        matched_prof = None
        for k, v in cfg_profiles.items():
            if k.lower() == clean_m:
                matched_prof = (k, v)
                break

        if matched_prof:
            prof_k, prof_v = matched_prof
            if isinstance(prof_v, str):
                target_model = prof_v
                target_effort = None
            elif isinstance(prof_v, dict):
                target_model = prof_v.get("model")
                target_effort = prof_v.get("effort")
            else:
                raise ModelPolicyViolation(f"Invalid profile configuration for {prof_k!r}")
            resolved_profile_name = prof_k
            is_profile_resolution = True
        else:
            target_model = model.strip()
            is_profile_resolution = False

    else:
        # model is None hoặc 'auto'
        is_default_resolution = True
        target_model = cfg_default_model
        target_effort = cfg_default_effort
        is_profile_resolution = False

    # 2. CHỐT CHẶN: Fail-closed default config chứa free/contributor
    if is_default_resolution:
        if not target_model:
            if v_clean == "openrouter":
                target_model = "auto"
            else:
                raise ModelPolicyViolation(
                    f"Vendor {vendor!r} has no configured default model",
                    reason="no_default_model",
                )
        if is_contributor_model(target_model):
            raise ContributorModelBlocked(
                f"Default model {target_model!r} is a contributor model. Contributor models are strictly forbidden.",
                model=target_model,
            )
        if is_free_model(target_model):
            raise FreeModelBlocked(
                f"Default model {target_model!r} is a free model. Free models cannot be defaults.",
                model=target_model,
            )

    # 3. CHỐT CHẶN: Alias/Profile không được biến lựa chọn gián tiếp thành explicit đối với free model
    if is_profile_resolution:
        if is_contributor_model(target_model):
            raise ContributorModelBlocked(
                f"Contributor model {target_model!r} is strictly forbidden (selected via profile {resolved_profile_name!r})",
                model=target_model,
            )
        if is_free_model(target_model):
            raise FreeModelBlocked(
                f"Free model {target_model!r} cannot be selected indirectly via profile or alias {resolved_profile_name!r}",
                model=target_model,
            )

    # 4. Xác định source hiệu lực
    if source is not None:
        norm_s = source.value if isinstance(source, SelectionSource) else str(source).strip().lower()
        if is_default_resolution and norm_s == SelectionSource.EXPLICIT.value:
            # Lựa chọn auto/default không được coi là explicit
            effective_source = SelectionSource.DEFAULT
        else:
            effective_source = source
    else:
        if is_default_resolution:
            effective_source = SelectionSource.AUTO if (model and model.strip().lower() == "auto") else SelectionSource.DEFAULT
        else:
            effective_source = SelectionSource.EXPLICIT

    # 5. Xác định provider hiệu lực
    effective_provider = provider or cfg_provider
    if not effective_provider and v_clean in GO_VENDORS:
        effective_provider = GO_PROVIDER

    # 6. Xác định effort hiệu lực
    effective_effort = effort or target_effort or cfg_default_effort
    if v_clean in GO_VENDORS or effective_provider == GO_PROVIDER:
        clean_base = target_model.split(":")[0].split("/")[-1].strip().lower()
        if clean_base.endswith("-free"):
            clean_base = clean_base[:-5]
        if clean_base in GO_APPROVED_PROFILES and not effective_effort:
            effective_effort = GO_APPROVED_PROFILES[clean_base]

    # 7. Phân tích cú pháp selector bằng parse_model_selector
    selector = parse_model_selector(
        raw=target_model,
        default_provider=effective_provider,
        explicit_provider=provider,
        explicit_variant=effort,
        default_variant=effective_effort,
    )

    # 8. Thực thi chính sách an toàn qua model_policy
    decision = check_model_policy(
        selector=selector,
        vendor=v_clean,
        provider=effective_provider,
        source=effective_source,
        catalog_models=catalog_models,
        allow_unknown=allow_unknown,
    )

    if decision.is_blocked:
        reason = decision.reason or "policy_violation"
        msg = decision.warnings[0] if decision.warnings else f"Model policy blocked with reason: {reason}"
        raw_val = selector.raw

        if reason == "malformed_selector":
            raise MalformedSelectorError(msg, raw=raw_val)
        if reason == "conflicting_provider":
            raise ConflictingProviderError(msg, raw=raw_val, provider=provider)
        if reason == "invalid_source":
            raise InvalidSourceError(msg, source=str(effective_source), model=decision.selector.model)
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

    final_sel = decision.selector

    return ResolvedTarget(
        vendor=v_clean,
        model=final_sel.model,
        provider=final_sel.provider or effective_provider,
        effort=final_sel.variant or effective_effort,
        profile=resolved_profile_name,
        source=effective_source.value if isinstance(effective_source, SelectionSource) else str(effective_source),
        selector=final_sel,
        warnings=list(decision.warnings),
        quota_group=cfg_quota_group,
        zdr=cfg_zdr,
    )


resolve_model = resolve_vendor_model
