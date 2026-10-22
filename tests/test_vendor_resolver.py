"""Unit tests for bin/lib/vendor_config.py and resolve_vendor_model.

Kiểm tra:
- Resolver chung model/provider/effort/profile/source sử dụng model_policy.
- Default models và effort của các vendor:
  * codex: gpt-6.1-sol (effort low)
  * dsh: deepseek-v4-pro (effort high)
  * agy: gemini-3.8-flash-high
  * opencode / hermes: deepseek-v4.1-flash (effort high, provider opencode-go, quota_group opencode-go)
- Profiles / hồ sơ:
  * agy: kho=gemini-4-argon-high, claude=claude-sonnet-5-5-medium, claude-opus=claude-opus-5-5-low, oss=gpt-oss-120b-medium
  * opencode / hermes: glm-5.3-flash (effort max)
- ZDR metadata của DeepSeek (dsh, opencode, hermes): expiry 2026-10-31, permanent=False.
- Injected cfg độc lập không phụ thuộc file đĩa.
- Fail-closed guards:
  * Default config chứa free hoặc contributor model bị chặn (fail-closed).
  * Alias / profile không được biến lựa chọn gián tiếp thành explicit đối với model free.
  * allow_unknown=True KHÔNG bypass contributor, free, hay unapproved Go profile/provider.
- Xung đột (conflicts):
  * Profile và model không khớp.
  * Variant trong selector và explicit effort mâu thuẫn.
  * Provider trong selector và explicit provider mâu thuẫn.
  * Provider không hợp lệ cho Go adapter.
"""
from __future__ import annotations

import pytest

from lib.model_policy import (
    ConflictingProviderError,
    ContributorModelBlocked,
    FreeModelBlocked,
    MalformedSelectorError,
    ModelPolicyViolation,
    SelectionSource,
    UnapprovedProfileError,
    UnapprovedProviderError,
)
from lib.vendor_config import (
    ResolvedModel,
    ResolvedTarget,
    default_effort,
    default_model,
    load_vendor_config,
    resolve_model,
    resolve_vendor_model,
    vendor_names,
    vendor_profiles,
    vendor_provider,
    vendor_quota_group,
    vendor_zdr,
)


# ===========================================================================
# 1. Default Resolution và Vendor Defaults
# ===========================================================================

class TestResolverDefaultsAndConfig:
    def test_codex_default_model_and_effort(self):
        res = resolve_vendor_model("codex")
        assert res.vendor == "codex"
        assert res.model == "gpt-6.1-sol"
        assert res.effort == "low"
        assert res.source == "default"
        assert res.canonical_name == "gpt-6.1-sol"

    def test_dsh_default_model_and_effort(self):
        res = resolve_vendor_model("dsh")
        assert res.vendor == "dsh"
        assert res.model == "deepseek-v4-pro"
        assert res.effort == "high"
        assert res.source == "default"
        assert res.zdr is not None
        assert res.zdr.get("expiry") == "2026-10-31"
        assert res.zdr.get("permanent") is False

    def test_agy_default_model(self):
        res = resolve_vendor_model("agy")
        assert res.vendor == "agy"
        assert res.model == "gemini-3.8-flash-high"
        assert res.source == "default"

    def test_opencode_default_model_and_provider(self):
        res = resolve_vendor_model("opencode")
        assert res.vendor == "opencode"
        assert res.model == "deepseek-v4.1-flash"
        assert res.effort == "high"
        assert res.provider == "opencode-go"
        assert res.quota_group == "opencode-go"
        assert res.source == "default"
        assert res.canonical_name == "opencode-go/deepseek-v4.1-flash"
        assert res.zdr is not None
        assert res.zdr.get("expiry") == "2026-10-31"

    def test_hermes_default_model_and_provider(self):
        res = resolve_vendor_model("hermes")
        assert res.vendor == "hermes"
        assert res.model == "deepseek-v4.1-flash"
        assert res.effort == "high"
        assert res.provider == "opencode-go"
        assert res.quota_group == "opencode-go"
        assert res.source == "default"
        assert res.zdr is not None
        assert res.zdr.get("expiry") == "2026-10-31"

    def test_grok_default_model(self):
        res = resolve_vendor_model("grok")
        assert res.vendor == "grok"
        assert res.model == "grok-4.6"
        assert res.source == "default"

    def test_claude_default_model(self):
        res = resolve_vendor_model("claude")
        assert res.vendor == "claude"
        assert res.model == "claude-opus-5"
        assert res.source == "default"

    def test_gemini_chua_kiem_raises_when_no_explicit_model(self):
        # Gemini có default_model: CHUA_KIEM -> không có default hợp lệ
        with pytest.raises(ModelPolicyViolation) as exc_info:
            resolve_vendor_model("gemini")
        assert exc_info.value.reason == "no_default_model"

    def test_resolve_with_auto_string(self):
        res = resolve_vendor_model("codex", "auto")
        assert res.model == "gpt-6.1-sol"
        assert res.source == "auto"

    def test_resolve_model_alias_callable(self):
        # resolve_model là alias của resolve_vendor_model
        assert resolve_model is resolve_vendor_model
        res = resolve_model("codex")
        assert res.model == "gpt-6.1-sol"


# ===========================================================================
# 2. Hồ sơ / Profiles Resolution
# ===========================================================================

class TestResolverProfiles:
    def test_agy_profile_kho(self):
        res = resolve_vendor_model("agy", profile="kho")
        assert res.model == "gemini-4-argon-high"
        assert res.profile == "kho"

    def test_agy_profile_claude(self):
        res = resolve_vendor_model("agy", profile="claude")
        assert res.model == "claude-sonnet-5-5-medium"
        assert res.profile == "claude"

    def test_agy_profile_claude_opus(self):
        res = resolve_vendor_model("agy", profile="claude-opus")
        assert res.model == "claude-opus-5-5-low"
        assert res.profile == "claude-opus"

    def test_agy_profile_oss(self):
        res = resolve_vendor_model("agy", profile="oss")
        assert res.model == "gpt-oss-120b-medium"
        assert res.profile == "oss"

    def test_agy_profile_via_model_alias(self):
        # Truyền model="kho" tự động nhận diện alias hồ sơ kho
        res = resolve_vendor_model("agy", "kho")
        assert res.model == "gemini-4-argon-high"
        assert res.profile == "kho"

    def test_agy_profile_claude_via_model_alias(self):
        res = resolve_vendor_model("agy", "claude")
        assert res.model == "claude-sonnet-5-5-medium"
        assert res.profile == "claude"

    def test_opencode_profile_glm_flash_effort_max(self):
        res = resolve_vendor_model("opencode", profile="glm-5.3-flash")
        assert res.model == "glm-5.3-flash"
        assert res.effort == "max"
        assert res.provider == "opencode-go"
        assert res.profile == "glm-5.3-flash"

    def test_opencode_profile_glm_flash_via_model_alias(self):
        res = resolve_vendor_model("opencode", "glm-5.3-flash")
        assert res.model == "glm-5.3-flash"
        assert res.effort == "max"
        assert res.provider == "opencode-go"

    def test_hermes_profile_glm_flash_effort_max(self):
        res = resolve_vendor_model("hermes", profile="glm-5.3-flash")
        assert res.model == "glm-5.3-flash"
        assert res.effort == "max"
        assert res.provider == "opencode-go"

    def test_profile_case_insensitivity(self):
        res = resolve_vendor_model("agy", profile="KhO")
        assert res.model == "gemini-4-argon-high"
        assert res.profile == "kho"

        res_glm = resolve_vendor_model("opencode", profile="GLM-5.3-FLASH")
        assert res_glm.model == "glm-5.3-flash"
        assert res_glm.effort == "max"

    def test_unknown_profile_raises_unapproved(self):
        with pytest.raises(UnapprovedProfileError):
            resolve_vendor_model("agy", profile="non_existent_profile")


# ===========================================================================
# 3. Explicit Model & Effort Overrides
# ===========================================================================

class TestResolverExplicitAndEffort:
    def test_explicit_model_and_effort_override(self):
        res = resolve_vendor_model("opencode", model="deepseek-v4.1-flash", effort="low")
        assert res.model == "deepseek-v4.1-flash"
        assert res.effort == "low"
        assert res.provider == "opencode-go"
        assert res.source == "explicit"

    def test_explicit_variant_in_model_selector(self):
        res = resolve_vendor_model("opencode", model="opencode-go/deepseek-v4.1-flash:high")
        assert res.model == "deepseek-v4.1-flash"
        assert res.effort == "high"
        assert res.provider == "opencode-go"
        assert res.full_target == "opencode-go/deepseek-v4.1-flash:high"

    def test_explicit_free_model_allowed_when_source_is_explicit(self):
        # Tuan chốt: free model được chọn tường minh
        res = resolve_vendor_model("opencode", model="deepseek-v4.1-flash-free", source=SelectionSource.EXPLICIT)
        assert res.model == "deepseek-v4.1-flash-free"
        assert res.provider == "opencode-go"
        assert res.source == "explicit"


# ===========================================================================
# 4. Injected Config Tests (Độc lập file đĩa)
# ===========================================================================

class TestResolverInjectedConfig:
    @pytest.fixture
    def injected_cfg(self):
        return {
            "schema_version": 3,
            "vendors": {
                "custom_vendor": {
                    "provider": "custom-provider",
                    "quota_group": "custom-group",
                    "default_model": "custom-model-v1",
                    "default_effort": "medium",
                    "profiles": {
                        "fast": "custom-model-fast",
                        "heavy": {
                            "model": "custom-model-heavy",
                            "effort": "max",
                        },
                    },
                    "zdr": {
                        "supported": True,
                        "expiry": "2026-10-31",
                        "permanent": False,
                    },
                }
            },
        }

    def test_injected_cfg_default_resolution(self, injected_cfg):
        res = resolve_vendor_model("custom_vendor", cfg=injected_cfg)
        assert res.vendor == "custom_vendor"
        assert res.model == "custom-model-v1"
        assert res.effort == "medium"
        assert res.provider == "custom-provider"
        assert res.quota_group == "custom-group"
        assert res.zdr["expiry"] == "2026-10-31"

    def test_injected_cfg_profile_string(self, injected_cfg):
        res = resolve_vendor_model("custom_vendor", profile="fast", cfg=injected_cfg)
        assert res.model == "custom-model-fast"
        assert res.profile == "fast"

    def test_injected_cfg_profile_dict(self, injected_cfg):
        res = resolve_vendor_model("custom_vendor", profile="heavy", cfg=injected_cfg)
        assert res.model == "custom-model-heavy"
        assert res.effort == "max"
        assert res.profile == "heavy"

    def test_injected_cfg_missing_default_raises(self):
        cfg = {"schema_version": 3, "vendors": {"empty_vendor": {}}}
        with pytest.raises(ModelPolicyViolation) as exc_info:
            resolve_vendor_model("empty_vendor", cfg=cfg)
        assert exc_info.value.reason == "no_default_model"


# ===========================================================================
# 5. Fail-Closed Guards (Security & Policy Enforcement)
# ===========================================================================

class TestResolverFailClosedGuards:
    def test_default_config_containing_free_model_fails_closed(self):
        # Default config chứa free model phải bị chặn ngay cả khi gọi auto
        bad_cfg = {
            "schema_version": 3,
            "vendors": {
                "opencode": {
                    "provider": "opencode-go",
                    "default_model": "deepseek-v4.1-flash-free",
                }
            },
        }
        with pytest.raises(FreeModelBlocked):
            resolve_vendor_model("opencode", cfg=bad_cfg)

        with pytest.raises(FreeModelBlocked):
            resolve_vendor_model("opencode", "auto", cfg=bad_cfg)

    def test_default_config_free_model_cannot_be_bypassed_with_source_explicit(self):
        # Caller cố tình truyền source="explicit" khi gọi default/auto không qua mặt được
        bad_cfg = {
            "schema_version": 3,
            "vendors": {
                "opencode": {
                    "provider": "opencode-go",
                    "default_model": "deepseek-v4.1-flash-free",
                }
            },
        }
        with pytest.raises(FreeModelBlocked):
            resolve_vendor_model("opencode", "auto", source="explicit", cfg=bad_cfg)

    def test_default_config_containing_contributor_model_fails_closed(self):
        # Default config chứa contributor model phải bị chặn
        bad_cfg = {
            "schema_version": 3,
            "vendors": {
                "codex": {
                    "default_model": "gpt-6.1-sol-contributor",
                }
            },
        }
        with pytest.raises(ContributorModelBlocked):
            resolve_vendor_model("codex", cfg=bad_cfg)

    def test_profile_pointing_to_free_model_fails_closed(self):
        # Alias/Profile không được biến lựa chọn gián tiếp thành explicit
        bad_cfg = {
            "schema_version": 3,
            "vendors": {
                "opencode": {
                    "provider": "opencode-go",
                    "default_model": "deepseek-v4.1-flash",
                    "profiles": {
                        "sneaky_free": "deepseek-v4.1-flash-free",
                    },
                }
            },
        }
        with pytest.raises(FreeModelBlocked):
            resolve_vendor_model("opencode", profile="sneaky_free", cfg=bad_cfg)

        # Kể cả caller truyền source="explicit"
        with pytest.raises(FreeModelBlocked):
            resolve_vendor_model("opencode", profile="sneaky_free", source="explicit", cfg=bad_cfg)

    def test_alias_model_pointing_to_free_model_fails_closed(self):
        bad_cfg = {
            "schema_version": 3,
            "vendors": {
                "opencode": {
                    "provider": "opencode-go",
                    "default_model": "deepseek-v4.1-flash",
                    "profiles": {
                        "free_alias": "deepseek-v4.1-flash-free",
                    },
                }
            },
        }
        with pytest.raises(FreeModelBlocked):
            resolve_vendor_model("opencode", "free_alias", cfg=bad_cfg)

    def test_profile_pointing_to_contributor_fails_closed(self):
        bad_cfg = {
            "schema_version": 3,
            "vendors": {
                "agy": {
                    "default_model": "gemini-3.8-flash-high",
                    "profiles": {
                        "bad_profile": "gemini-contributor-high",
                    },
                }
            },
        }
        with pytest.raises(ContributorModelBlocked):
            resolve_vendor_model("agy", profile="bad_profile", cfg=bad_cfg)

    def test_allow_unknown_does_not_bypass_contributor(self):
        # allow_unknown=True KHÔNG bypass contributor model
        with pytest.raises(ContributorModelBlocked):
            resolve_vendor_model("codex", model="gpt-contributor", allow_unknown=True)

    def test_allow_unknown_does_not_bypass_free_on_default(self):
        bad_cfg = {
            "schema_version": 3,
            "vendors": {
                "opencode": {
                    "provider": "opencode-go",
                    "default_model": "deepseek-v4.1-flash-free",
                }
            },
        }
        with pytest.raises(FreeModelBlocked):
            resolve_vendor_model("opencode", allow_unknown=True, cfg=bad_cfg)

    def test_allow_unknown_does_not_bypass_unapproved_go_profile(self):
        with pytest.raises(UnapprovedProfileError):
            resolve_vendor_model("opencode", model="qwen-72b", allow_unknown=True)


# ===========================================================================
# 6. Conflicts & Malformed Selectors
# ===========================================================================

class TestResolverConflicts:
    def test_conflicting_profile_and_model(self):
        # Profile kho resolves gemini-4-argon-high, nhưng model requested là claude-sonnet
        with pytest.raises(ModelPolicyViolation) as exc_info:
            resolve_vendor_model("agy", profile="kho", model="claude-sonnet-5-5-medium")
        assert exc_info.value.reason == "conflicting_profile"

    def test_matching_profile_and_model_succeeds(self):
        # Profile kho và model gemini-4-argon-high khớp nhau -> thành công
        res = resolve_vendor_model("agy", profile="kho", model="gemini-4-argon-high")
        assert res.model == "gemini-4-argon-high"
        assert res.profile == "kho"

    def test_conflicting_variant_in_selector_and_explicit_effort(self):
        with pytest.raises(MalformedSelectorError):
            resolve_vendor_model("opencode", model="deepseek-v4.1-flash:high", effort="low")

    def test_conflicting_provider_in_selector_and_explicit_provider(self):
        with pytest.raises(ConflictingProviderError):
            resolve_vendor_model(
                "opencode",
                model="opencode-go/deepseek-v4.1-flash",
                provider="openrouter",
            )

    def test_unapproved_go_provider(self):
        with pytest.raises(UnapprovedProviderError):
            resolve_vendor_model("opencode", model="deepseek-v4.1-flash", provider="openrouter")

    def test_empty_vendor_raises_malformed(self):
        with pytest.raises(MalformedSelectorError):
            resolve_vendor_model("")


# ===========================================================================
# 7. Helper Functions & Metadata
# ===========================================================================

class TestResolverHelperFunctions:
    def test_vendor_names_contains_new_vendors(self):
        names = vendor_names()
        assert "opencode" in names
        assert "hermes" in names
        assert "agy" in names
        assert "dsh" in names
        assert "codex" in names

    def test_default_model_function(self):
        assert default_model("codex") == "gpt-6.1-sol"
        assert default_model("dsh") == "deepseek-v4-pro"
        assert default_model("agy") == "gemini-3.8-flash-high"
        assert default_model("opencode") == "deepseek-v4.1-flash"
        assert default_model("hermes") == "deepseek-v4.1-flash"
        assert default_model("gemini") is None

    def test_default_effort_function(self):
        assert default_effort("codex") == "low"
        assert default_effort("dsh") == "high"
        assert default_effort("opencode") == "high"
        assert default_effort("hermes") == "high"

    def test_vendor_provider_function(self):
        assert vendor_provider("opencode") == "opencode-go"
        assert vendor_provider("hermes") == "opencode-go"
        assert vendor_provider("agy") is None

    def test_vendor_quota_group_function(self):
        assert vendor_quota_group("opencode") == "opencode-go"
        assert vendor_quota_group("hermes") == "opencode-go"

    def test_vendor_profiles_function(self):
        agy_profs = vendor_profiles("agy")
        assert "kho" in agy_profs
        assert "claude" in agy_profs
        assert "claude-opus" in agy_profs
        assert "oss" in agy_profs

    def test_vendor_zdr_function(self):
        zdr_dsh = vendor_zdr("dsh")
        assert zdr_dsh is not None
        assert zdr_dsh.get("expiry") == "2026-10-31"
        assert zdr_dsh.get("permanent") is False

        zdr_oc = vendor_zdr("opencode")
        assert zdr_oc is not None
        assert zdr_oc.get("expiry") == "2026-10-31"


# ===========================================================================
# 8. Deterministic Resolution cho 2 Go Adapters (opencode & hermes)
# ===========================================================================

class TestGoAdaptersDeterministicResolution:
    @pytest.mark.parametrize("vendor", ["opencode", "hermes"])
    def test_glm_flash_bare_and_prefixed_deterministic_max(self, vendor):
        """Bare glm-5.3-flash và opencode-go/glm-5.3-flash cùng cho effort max."""
        res_bare = resolve_vendor_model(vendor, "glm-5.3-flash")
        res_pref = resolve_vendor_model(vendor, "opencode-go/glm-5.3-flash")

        assert res_bare.effort == "max"
        assert res_pref.effort == "max"
        assert res_bare.model == "glm-5.3-flash"
        assert res_pref.model == "glm-5.3-flash"
        assert res_bare.provider == "opencode-go"
        assert res_pref.provider == "opencode-go"
        assert res_bare.canonical_name == "opencode-go/glm-5.3-flash"
        assert res_pref.canonical_name == "opencode-go/glm-5.3-flash"
        assert res_bare.full_target == "opencode-go/glm-5.3-flash:max"
        assert res_pref.full_target == "opencode-go/glm-5.3-flash:max"
        assert res_bare.canonical_name == res_pref.canonical_name
        assert res_bare.full_target == res_pref.full_target

    @pytest.mark.parametrize("vendor", ["opencode", "hermes"])
    def test_deepseek_flash_bare_and_prefixed_deterministic_high(self, vendor):
        """Bare deepseek-v4.1-flash và opencode-go/deepseek-v4.1-flash cùng cho effort high."""
        res_bare = resolve_vendor_model(vendor, "deepseek-v4.1-flash")
        res_pref = resolve_vendor_model(vendor, "opencode-go/deepseek-v4.1-flash")

        assert res_bare.effort == "high"
        assert res_pref.effort == "high"
        assert res_bare.model == "deepseek-v4.1-flash"
        assert res_pref.model == "deepseek-v4.1-flash"
        assert res_bare.provider == "opencode-go"
        assert res_pref.provider == "opencode-go"
        assert res_bare.canonical_name == "opencode-go/deepseek-v4.1-flash"
        assert res_pref.canonical_name == "opencode-go/deepseek-v4.1-flash"
        assert res_bare.full_target == "opencode-go/deepseek-v4.1-flash:high"
        assert res_pref.full_target == "opencode-go/deepseek-v4.1-flash:high"

    @pytest.mark.parametrize("vendor", ["opencode", "hermes"])
    def test_case_insensitivity_bare_and_prefixed(self, vendor):
        """Không phân biệt hoa thường với cả bare lẫn prefixed slug."""
        res_upper_bare = resolve_vendor_model(vendor, "GLM-5.3-FLASH")
        res_upper_pref = resolve_vendor_model(vendor, "OPENCODE-GO/GLM-5.3-FLASH")
        res_mixed_pref = resolve_vendor_model(vendor, "OpEnCoDe-Go/GlM-5.3-FlAsH")

        for r in (res_upper_bare, res_upper_pref, res_mixed_pref):
            assert r.model == "glm-5.3-flash"
            assert r.provider == "opencode-go"
            assert r.effort == "max"
            assert r.canonical_name == "opencode-go/glm-5.3-flash"
            assert r.full_target == "opencode-go/glm-5.3-flash:max"

    @pytest.mark.parametrize("vendor", ["opencode", "hermes"])
    def test_variant_suffix_in_selector_string(self, vendor):
        """Variant suffix (:high, :max, :low) trong selector string được tôn trọng."""
        res_high_bare = resolve_vendor_model(vendor, "glm-5.3-flash:high")
        res_high_pref = resolve_vendor_model(vendor, "opencode-go/glm-5.3-flash:high")
        assert res_high_bare.effort == "high"
        assert res_high_pref.effort == "high"
        assert res_high_bare.full_target == "opencode-go/glm-5.3-flash:high"
        assert res_high_pref.full_target == "opencode-go/glm-5.3-flash:high"

        res_max_bare = resolve_vendor_model(vendor, "glm-5.3-flash:max")
        res_max_pref = resolve_vendor_model(vendor, "opencode-go/glm-5.3-flash:max")
        assert res_max_bare.effort == "max"
        assert res_max_pref.effort == "max"
        assert res_max_bare.full_target == "opencode-go/glm-5.3-flash:max"
        assert res_max_pref.full_target == "opencode-go/glm-5.3-flash:max"

        res_low_bare = resolve_vendor_model(vendor, "glm-5.3-flash:low")
        res_low_pref = resolve_vendor_model(vendor, "opencode-go/glm-5.3-flash:low")
        assert res_low_bare.effort == "low"
        assert res_low_pref.effort == "low"
        assert res_low_bare.full_target == "opencode-go/glm-5.3-flash:low"
        assert res_low_pref.full_target == "opencode-go/glm-5.3-flash:low"

        # Mixed case kèm variant
        res_mixed = resolve_vendor_model(vendor, "OpEnCoDe-Go/GlM-5.3-FlAsH:HiGh")
        assert res_mixed.effort == "high"
        assert res_mixed.full_target == "opencode-go/glm-5.3-flash:high"

    @pytest.mark.parametrize("vendor", ["opencode", "hermes"])
    def test_explicit_effort_override_valid(self, vendor):
        """Explicit --effort vẫn ưu tiên hợp lệ đối với cả bare và prefixed."""
        res_bare_low = resolve_vendor_model(vendor, "glm-5.3-flash", effort="low")
        assert res_bare_low.effort == "low"

        res_pref_low = resolve_vendor_model(vendor, "opencode-go/glm-5.3-flash", effort="low")
        assert res_pref_low.effort == "low"

        res_bare_high = resolve_vendor_model(vendor, "glm-5.3-flash", effort="high")
        assert res_bare_high.effort == "high"

        res_pref_high = resolve_vendor_model(vendor, "opencode-go/glm-5.3-flash", effort="high")
        assert res_pref_high.effort == "high"

        res_ds_low = resolve_vendor_model(vendor, "deepseek-v4.1-flash", effort="low")
        assert res_ds_low.effort == "low"

        res_ds_pref_max = resolve_vendor_model(vendor, "opencode-go/deepseek-v4.1-flash", effort="max")
        assert res_ds_pref_max.effort == "max"

    @pytest.mark.parametrize("vendor", ["opencode", "hermes"])
    def test_variant_suffix_conflict_raises_malformed(self, vendor):
        """Variant suffix và explicit --effort mâu thuẫn phải raise conflict rõ ràng."""
        with pytest.raises(MalformedSelectorError) as exc_bare:
            resolve_vendor_model(vendor, "glm-5.3-flash:high", effort="low")
        assert "Conflicting variant" in str(exc_bare.value)

        with pytest.raises(MalformedSelectorError) as exc_pref:
            resolve_vendor_model(vendor, "opencode-go/glm-5.3-flash:high", effort="low")
        assert "Conflicting variant" in str(exc_pref.value)

        with pytest.raises(MalformedSelectorError) as exc_max_low:
            resolve_vendor_model(vendor, "opencode-go/glm-5.3-flash:max", effort="low")
        assert "Conflicting variant" in str(exc_max_low.value)

        with pytest.raises(MalformedSelectorError) as exc_bare_max_high:
            resolve_vendor_model(vendor, "glm-5.3-flash:max", effort="high")
        assert "Conflicting variant" in str(exc_bare_max_high.value)

    @pytest.mark.parametrize("vendor", ["opencode", "hermes"])
    def test_variant_suffix_matching_explicit_effort_succeeds(self, vendor):
        """Variant suffix và explicit --effort khớp nhau thì thành công."""
        res_high = resolve_vendor_model(vendor, "opencode-go/glm-5.3-flash:high", effort="high")
        assert res_high.effort == "high"

        res_max = resolve_vendor_model(vendor, "glm-5.3-flash:max", effort="max")
        assert res_max.effort == "max"

    @pytest.mark.parametrize("vendor", ["opencode", "hermes"])
    def test_default_config_altered_does_not_bypass_policy(self, vendor):
        """Cấu hình default bị thay đổi không được vượt policy."""
        # 1. Unapproved model trong default_model bị chặn
        bad_cfg_model = {
            "schema_version": 3,
            "vendors": {
                vendor: {
                    "provider": "opencode-go",
                    "default_model": "qwen-72b",
                }
            },
        }
        with pytest.raises(UnapprovedProfileError):
            resolve_vendor_model(vendor, cfg=bad_cfg_model)

        # 2. Unapproved provider trong config bị chặn
        bad_cfg_provider = {
            "schema_version": 3,
            "vendors": {
                vendor: {
                    "provider": "openrouter",
                    "default_model": "deepseek-v4.1-flash",
                }
            },
        }
        with pytest.raises(UnapprovedProviderError):
            resolve_vendor_model(vendor, cfg=bad_cfg_provider)

        # 3. Default model là free model bị chặn (fail-closed)
        bad_cfg_free = {
            "schema_version": 3,
            "vendors": {
                vendor: {
                    "provider": "opencode-go",
                    "default_model": "glm-5.3-flash-free",
                }
            },
        }
        with pytest.raises(FreeModelBlocked):
            resolve_vendor_model(vendor, cfg=bad_cfg_free)

        # 4. Default model là contributor model bị chặn
        bad_cfg_contrib = {
            "schema_version": 3,
            "vendors": {
                vendor: {
                    "provider": "opencode-go",
                    "default_model": "glm-5.3-flash-contributor",
                }
            },
        }
        with pytest.raises(ContributorModelBlocked):
            resolve_vendor_model(vendor, cfg=bad_cfg_contrib)

        # 5. Default model đổi sang glm-5.3-flash nhưng default_effort là high
        # Profile default max theo model canonical phải đi trước vendor default high
        altered_cfg_glm_default = {
            "schema_version": 3,
            "vendors": {
                vendor: {
                    "provider": "opencode-go",
                    "default_model": "glm-5.3-flash",
                    "default_effort": "high",
                }
            },
        }
        res = resolve_vendor_model(vendor, cfg=altered_cfg_glm_default)
        assert res.model == "glm-5.3-flash"
        assert res.effort == "max"
        assert res.provider == "opencode-go"

