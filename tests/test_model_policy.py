"""Unit tests for bin/lib/model_policy.py.

Kiểm tra:
- Chuẩn hoá selector: bare, provider/model, variant, whitespace, casing.
- Malformed / ambiguous selectors bị blocked (MalformedSelectorError).
- Chốt chặn Contributor: cấm tuyệt đối, không cho bypass kể cả allow_unknown=True.
- Chốt chặn Free: chỉ cho phép chọn tường minh (source='explicit'), cấm default/auto/failover.
- Chốt chặn OpenRouter: router/free chưa rõ đích bị blocked, model đích cụ thể được duyệt.
- Go adapter (opencode, hermes): chỉ chấp nhận provider opencode-go.
- Go profiles: deepseek-v4.1-flash (high) và glm-5.3-flash (max); tự gán default effort.
- Catalog unknown: là advisory warning cho vendor khác, không whitelist cứng.
- Bypass tests: thử qua mặt bằng casing, whitespace, alias, config flag.
"""
from __future__ import annotations

import pytest

from bin.lib.model_policy import (
    DEFAULT_GO_PROFILE,
    GO_APPROVED_PROFILES,
    GO_PROVIDER,
    VALID_SOURCES,
    VALID_VARIANTS,
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
    is_openrouter_unresolved,
    parse_model_selector,
    resolve_go_profile,
)


# ===========================================================================
# 1. Chuẩn hoá selector (Positive Tests)
# ===========================================================================

class TestParseModelSelector:
    def test_parse_bare_model(self):
        sel = parse_model_selector("deepseek-v4.1-flash")
        assert sel.model == "deepseek-v4.1-flash"
        assert sel.provider is None
        assert sel.variant is None
        assert sel.canonical_name == "deepseek-v4.1-flash"
        assert sel.full_target == "deepseek-v4.1-flash"
        assert not sel.is_free
        assert not sel.is_contributor

    def test_parse_provider_and_model(self):
        sel = parse_model_selector("opencode-go/deepseek-v4.1-flash")
        assert sel.provider == "opencode-go"
        assert sel.model == "deepseek-v4.1-flash"
        assert sel.canonical_name == "opencode-go/deepseek-v4.1-flash"

    def test_parse_selector_with_variant(self):
        sel = parse_model_selector("opencode-go/deepseek-v4.1-flash:high")
        assert sel.provider == "opencode-go"
        assert sel.model == "deepseek-v4.1-flash"
        assert sel.variant == "high"
        assert sel.full_target == "opencode-go/deepseek-v4.1-flash:high"

    def test_parse_whitespace_and_case_normalization(self):
        sel = parse_model_selector("  OpEnCoDe-Go / DeepSeek-V4.1-Flash : High  ")
        assert sel.provider == "opencode-go"
        assert sel.model == "deepseek-v4.1-flash"
        assert sel.variant == "high"

    def test_parse_openrouter_scoped_model(self):
        sel = parse_model_selector("openrouter/minimax/minimax-m3:free")
        assert sel.provider == "openrouter"
        assert sel.model == "minimax/minimax-m3:free"
        assert sel.is_free is True
        assert sel.variant is None

    def test_parse_openrouter_scoped_model_with_variant(self):
        sel = parse_model_selector("openrouter/minimax/minimax-m3:free:high")
        assert sel.provider == "openrouter"
        assert sel.model == "minimax/minimax-m3:free"
        assert sel.variant == "high"
        assert sel.is_free is True

    def test_parse_with_default_provider_and_variant(self):
        sel = parse_model_selector(
            "glm-5.3-flash",
            default_provider="opencode-go",
            default_variant="max",
        )
        assert sel.provider == "opencode-go"
        assert sel.model == "glm-5.3-flash"
        assert sel.variant == "max"

    def test_parse_explicit_matching_provider_and_variant(self):
        sel = parse_model_selector(
            "opencode-go/deepseek-v4.1-flash:high",
            explicit_provider="opencode-go",
            explicit_variant="high",
        )
        assert sel.provider == "opencode-go"
        assert sel.variant == "high"


# ===========================================================================
# 2. Malformed / Ambiguous Selectors (Negative Tests)
# ===========================================================================

class TestMalformedSelectors:
    @pytest.mark.parametrize("bad_input", [
        "",
        "   ",
        "\t\n",
        "model\0null",
        "deepseek\x1bflash",
    ])
    def test_reject_empty_or_control_chars(self, bad_input):
        with pytest.raises(MalformedSelectorError):
            parse_model_selector(bad_input)

    @pytest.mark.parametrize("bad_delimiter", [
        "//",
        "a//b",
        "/model",
        "provider/",
        "::",
        "a::b",
        ":high",
        "model:",
        "opencode-go//deepseek-v4.1-flash",
        "opencode-go/deepseek-v4.1-flash::high",
    ])
    def test_reject_duplicate_or_empty_delimiter_segments(self, bad_delimiter):
        with pytest.raises(MalformedSelectorError):
            parse_model_selector(bad_delimiter)

    def test_reject_internal_whitespace_in_token(self):
        with pytest.raises(MalformedSelectorError):
            parse_model_selector("deepseek v4.1 flash")
        with pytest.raises(MalformedSelectorError):
            parse_model_selector("open code/model")

    def test_reject_invalid_variant(self):
        with pytest.raises(MalformedSelectorError):
            parse_model_selector("deepseek-v4.1-flash:ultrafast")

    def test_reject_conflicting_variant(self):
        with pytest.raises(MalformedSelectorError, match="Conflicting variant"):
            parse_model_selector("deepseek-v4.1-flash:high", explicit_variant="low")

    def test_reject_conflicting_provider(self):
        with pytest.raises(MalformedSelectorError, match="Conflicting provider"):
            parse_model_selector("opencode-go/deepseek-v4.1-flash", explicit_provider="openrouter")

    def test_reject_ambiguous_multiple_slashes(self):
        with pytest.raises(MalformedSelectorError):
            parse_model_selector("provider/sub/model/extra")


# ===========================================================================
# 3. Contributor Policy (Hard Block + Bypass Attempts)
# ===========================================================================

class TestContributorPolicy:
    @pytest.mark.parametrize("contributor_slug", [
        "deepseek-v4.1-flash-contributor",
        "glm-5.3-flash-contributor",
        "gpt-6.1-sol-contributor",
        "claude-opus-5.5-contributor",
        "opencode-go/deepseek-v4.1-flash-contributor",
        "openrouter/deepseek-contributor:free",
    ])
    def test_contributor_is_strictly_blocked(self, contributor_slug):
        decision = check_model_policy(contributor_slug, source=SelectionSource.EXPLICIT)
        assert decision.is_blocked
        assert decision.reason == "contributor_model_blocked"

        with pytest.raises(ContributorModelBlocked):
            enforce_model_policy(contributor_slug, source=SelectionSource.EXPLICIT)

    def test_contributor_bypass_via_allow_unknown_flag(self):
        # Không cho phép vượt chốt kể cả allow_unknown=True
        decision = check_model_policy(
            "deepseek-v4.1-flash-contributor",
            source=SelectionSource.EXPLICIT,
            allow_unknown=True,
        )
        assert decision.is_blocked
        assert decision.reason == "contributor_model_blocked"

        with pytest.raises(ContributorModelBlocked):
            enforce_model_policy(
                "deepseek-v4.1-flash-contributor",
                source=SelectionSource.EXPLICIT,
                allow_unknown=True,
            )

    def test_contributor_bypass_via_casing_and_whitespace(self):
        sneaky = "   DEEPSEEK-V4.1-FLASH-CONTRIBUTOR : High   "
        decision = check_model_policy(sneaky, source=SelectionSource.EXPLICIT)
        assert decision.is_blocked
        assert decision.reason == "contributor_model_blocked"

    def test_contributor_bypass_via_default_or_auto(self):
        # Cấm bất kể nguồn gọi
        for src in [SelectionSource.DEFAULT, SelectionSource.AUTO, SelectionSource.FAILOVER]:
            decision = check_model_policy("deepseek-contributor", source=src)
            assert decision.is_blocked
            assert decision.reason == "contributor_model_blocked"


# ===========================================================================
# 4. Free Model Policy (Explicit Only)
# ===========================================================================

class TestFreeModelPolicy:
    @pytest.mark.parametrize("free_slug", [
        "deepseek-v4.1-flash-free",
        "glm-5.3-flash-free",
    ])
    def test_free_model_allowed_only_when_explicit(self, free_slug):
        # Tường minh (CLI --model) cho non-OpenRouter free model -> CHO PHÉP (Tuan chốt 22/10)
        decision = check_model_policy(free_slug, source=SelectionSource.EXPLICIT)
        assert decision.is_allowed

        sel = enforce_model_policy(free_slug, source=SelectionSource.EXPLICIT)
        assert sel.is_free is True

    def test_openrouter_free_model_blocked_even_when_explicit(self):
        # OpenRouter :free bị chặn kể cả khi chọn tường minh (plan mục 94)
        decision = check_model_policy(
            "openrouter/minimax/minimax-m3:free",
            source=SelectionSource.EXPLICIT,
        )
        assert decision.is_blocked
        assert decision.reason == "openrouter_free_blocked"

        with pytest.raises(OpenRouterFreeBlocked):
            enforce_model_policy(
                "openrouter/minimax/minimax-m3:free",
                source=SelectionSource.EXPLICIT,
            )

    @pytest.mark.parametrize("bad_source", [
        SelectionSource.DEFAULT,
        SelectionSource.AUTO,
        SelectionSource.FAILOVER,
        "default",
        "auto",
        "failover",
    ])
    def test_free_model_blocked_on_implicit_selection(self, bad_source):
        free_slug = "deepseek-v4.1-flash-free"
        decision = check_model_policy(free_slug, source=bad_source)
        assert decision.is_blocked
        assert decision.reason == "free_model_not_explicit"

        with pytest.raises(FreeModelBlocked):
            enforce_model_policy(free_slug, source=bad_source)

    def test_free_model_bypass_via_allow_unknown_on_default(self):
        # allow_unknown=True KHÔNG ĐƯỢC làm lọt free model vào default
        decision = check_model_policy(
            "deepseek-v4.1-flash-free",
            source=SelectionSource.DEFAULT,
            allow_unknown=True,
        )
        assert decision.is_blocked
        assert decision.reason == "free_model_not_explicit"

        with pytest.raises(FreeModelBlocked):
            enforce_model_policy(
                "deepseek-v4.1-flash-free",
                source=SelectionSource.DEFAULT,
                allow_unknown=True,
            )


# ===========================================================================
# 5. OpenRouter Router / Unresolved Destination Policy
# ===========================================================================

class TestOpenRouterPolicy:
    @pytest.mark.parametrize("router_slug", [
        "openrouter/auto",
        "openrouter/free",
        "openrouter/free-router",
        "openrouter/:free",
        "free-router",
        "auto",
    ])
    def test_unresolved_openrouter_router_blocked(self, router_slug):
        decision = check_model_policy(
            router_slug,
            provider="openrouter",
            source=SelectionSource.EXPLICIT,
        )
        assert decision.is_blocked
        assert decision.reason == "openrouter_unresolved_destination"

        with pytest.raises(UnresolvedDestinationError):
            enforce_model_policy(
                router_slug,
                provider="openrouter",
                source=SelectionSource.EXPLICIT,
            )

    def test_concrete_openrouter_model_allowed(self):
        # Model có đích xác định rõ ràng và không phải :free -> Cho phép
        sel = enforce_model_policy(
            "openrouter/minimax/minimax-m3",
            source=SelectionSource.EXPLICIT,
        )
        assert sel.provider == "openrouter"
        assert sel.model == "minimax/minimax-m3"
        assert sel.is_free is False

    @pytest.mark.parametrize("or_free_slug", [
        "openrouter/minimax/minimax-m3:free",
        "openrouter/meta-llama/llama-3-8b-instruct:free",
        "openrouter/google/gemma-2-9b-it:free",
    ])
    def test_concrete_openrouter_free_model_blocked(self, or_free_slug):
        # Plan mục 94: OpenRouter model cụ thể gắn :free cũng bị chặn kể cả explicit
        for src in [SelectionSource.EXPLICIT, SelectionSource.DEFAULT, SelectionSource.AUTO, SelectionSource.FAILOVER]:
            decision = check_model_policy(or_free_slug, source=src)
            assert decision.is_blocked
            assert decision.reason == "openrouter_free_blocked"

            with pytest.raises(OpenRouterFreeBlocked):
                enforce_model_policy(or_free_slug, source=src)


# ===========================================================================
# 6. Go Adapter Rules (Provider & Profiles)
# ===========================================================================

class TestGoAdapterPolicy:
    def test_go_adapter_permits_opencode_go_provider(self):
        # Vendor opencode/hermes dùng provider opencode-go -> Hợp lệ
        for v in ["opencode", "hermes"]:
            sel = enforce_model_policy(
                "deepseek-v4.1-flash",
                vendor=v,
                provider=GO_PROVIDER,
                source=SelectionSource.EXPLICIT,
            )
            assert sel.provider == GO_PROVIDER
            assert sel.model == "deepseek-v4.1-flash"
            assert sel.variant == "high"  # Tự động gán variant duyệt

    def test_go_adapter_rejects_unapproved_providers(self):
        # Chặn nếu Go adapter truyền provider khác ngoài opencode-go
        for v in ["opencode", "hermes"]:
            for bad_p in ["openrouter", "openai", "deepseek-direct", "ollama"]:
                decision = check_model_policy(
                    "deepseek-v4.1-flash",
                    vendor=v,
                    provider=bad_p,
                )
                assert decision.is_blocked
                assert decision.reason == "unapproved_go_provider"

                with pytest.raises(UnapprovedProviderError):
                    enforce_model_policy(
                        "deepseek-v4.1-flash",
                        vendor=v,
                        provider=bad_p,
                    )

    def test_go_approved_profile_deepseek(self):
        # deepseek-v4.1-flash default variant là high
        sel = enforce_model_policy(
            "deepseek-v4.1-flash",
            vendor="opencode",
            provider=GO_PROVIDER,
        )
        assert sel.model == "deepseek-v4.1-flash"
        assert sel.variant == "high"

    def test_go_approved_profile_glm(self):
        # glm-5.3-flash không truyền variant thì lấy max từ hồ sơ
        sel = enforce_model_policy(
            "glm-5.3-flash",
            vendor="hermes",
            provider=GO_PROVIDER,
        )
        assert sel.model == "glm-5.3-flash"
        assert sel.variant == "max"

    def test_go_rejects_unapproved_model_profile(self):
        # Model không thuộc 2 profile duyệt trên Go adapter -> Chặn
        decision = check_model_policy(
            "qwen3.8-max",
            vendor="opencode",
            provider=GO_PROVIDER,
        )
        assert decision.is_blocked
        assert decision.reason == "unapproved_go_profile"

        with pytest.raises(UnapprovedProfileError):
            enforce_model_policy(
                "qwen3.8-max",
                vendor="opencode",
                provider=GO_PROVIDER,
            )

    def test_resolve_go_profile_helper(self):
        m, v = resolve_go_profile("deepseek-v4.1-flash")
        assert m == "deepseek-v4.1-flash" and v == "high"

        m, v = resolve_go_profile("glm-5.3-flash")
        assert m == "glm-5.3-flash" and v == "max"

        with pytest.raises(UnapprovedProfileError):
            resolve_go_profile("claude-sonnet-5.5")


# ===========================================================================
# 7. Catalog Advisory (Non-Go Vendors)
# ===========================================================================

class TestCatalogAdvisory:
    def test_unknown_catalog_model_is_advisory_not_blocked(self):
        # Đối với các vendor khác (codex, agy, grok, claude...):
        # Model chưa có trong verified catalog chỉ là cảnh báo ADVISORY, không whitelist cứng.
        catalog = ["gpt-6.1-sol", "gpt-5.6-terra"]
        decision = check_model_policy(
            "gpt-6.5-turbo",
            vendor="codex",
            catalog_models=catalog,
        )
        assert decision.action == PolicyAction.WARN
        assert decision.is_allowed is True
        assert not decision.is_blocked
        assert any("advisory warning" in w for w in decision.warnings)

        # enforce_model_policy không ném ngoại lệ
        sel = enforce_model_policy(
            "gpt-6.5-turbo",
            vendor="codex",
            catalog_models=catalog,
        )
        assert sel.model == "gpt-6.5-turbo"

    def test_known_catalog_model_has_no_warnings(self):
        catalog = ["gpt-6.1-sol", "gpt-5.6-terra"]
        decision = check_model_policy(
            "gpt-6.1-sol",
            vendor="codex",
            catalog_models=catalog,
        )
        assert decision.action == PolicyAction.ALLOW
        assert len(decision.warnings) == 0


# ===========================================================================
# 8. Classification & Helper Functions
# ===========================================================================

class TestClassificationHelpers:
    def test_is_contributor_model(self):
        assert is_contributor_model("deepseek-v4.1-flash-contributor")
        assert is_contributor_model("CONTRIBUTOR")
        assert is_contributor_model("opencode-go/model-contributor")
        assert not is_contributor_model("deepseek-v4.1-flash")
        assert not is_contributor_model("glm-5.3-flash")

    def test_is_free_model(self):
        assert is_free_model("deepseek-v4.1-flash-free")
        assert is_free_model("minimax-m3:free")
        assert is_free_model("free")
        assert is_free_model("free-model")
        assert not is_free_model("deepseek-v4.1-flash")
        assert not is_free_model("freedom-model")

    def test_is_openrouter_unresolved(self):
        sel1 = parse_model_selector("openrouter/auto")
        assert is_openrouter_unresolved(sel1)

        sel2 = parse_model_selector("openrouter/free")
        assert is_openrouter_unresolved(sel2)

        sel3 = parse_model_selector("openrouter/minimax/minimax-m3:free")
        assert not is_openrouter_unresolved(sel3)


# ===========================================================================
# 9. Dataclass Bypass Attempts (Negative Tests)
# ===========================================================================

class TestDataclassBypassAttempts:
    def test_dataclass_post_init_recomputes_free_flag(self):
        # Caller tự dựng ModelSelector với is_free=False cho model free
        sel = ModelSelector(raw="deepseek-v4.1-flash-free", model="deepseek-v4.1-flash-free", is_free=False)
        assert sel.is_free is True

    def test_dataclass_forced_mutation_free_flag_blocked_on_default(self):
        # Caller dùng object.__setattr__ để ép is_free=False
        sel = ModelSelector(raw="deepseek-v4.1-flash-free", model="deepseek-v4.1-flash-free")
        object.__setattr__(sel, "is_free", False)
        assert sel.is_free is False

        # check_model_policy tái tính toán flags, không tin cậy cached is_free
        decision = check_model_policy(sel, source=SelectionSource.DEFAULT)
        assert decision.is_blocked
        assert decision.reason == "free_model_not_explicit"

        with pytest.raises(FreeModelBlocked):
            enforce_model_policy(sel, source=SelectionSource.DEFAULT)

    def test_dataclass_post_init_recomputes_contributor_flag(self):
        sel = ModelSelector(raw="deepseek-contributor", model="deepseek-contributor", is_contributor=False)
        assert sel.is_contributor is True

    def test_dataclass_forced_mutation_contributor_flag_blocked(self):
        sel = ModelSelector(raw="deepseek-contributor", model="deepseek-contributor")
        object.__setattr__(sel, "is_contributor", False)
        assert sel.is_contributor is False

        decision = check_model_policy(sel, source=SelectionSource.EXPLICIT)
        assert decision.is_blocked
        assert decision.reason == "contributor_model_blocked"

        with pytest.raises(ContributorModelBlocked):
            enforce_model_policy(sel, source=SelectionSource.EXPLICIT)

    def test_dataclass_post_init_recomputes_router_flag(self):
        sel = ModelSelector(raw="openrouter/auto", provider="openrouter", model="auto", is_router=False)
        assert sel.is_router is True

    def test_dataclass_forced_mutation_router_flag_blocked(self):
        sel = ModelSelector(raw="openrouter/auto", provider="openrouter", model="auto")
        object.__setattr__(sel, "is_router", False)
        assert sel.is_router is False

        decision = check_model_policy(sel, provider="openrouter", source=SelectionSource.EXPLICIT)
        assert decision.is_blocked
        assert decision.reason == "openrouter_unresolved_destination"

        with pytest.raises(UnresolvedDestinationError):
            enforce_model_policy(sel, provider="openrouter", source=SelectionSource.EXPLICIT)

    def test_dataclass_forced_mutation_openrouter_free_blocked(self):
        sel = ModelSelector(
            raw="openrouter/minimax/minimax-m3:free",
            provider="openrouter",
            model="minimax/minimax-m3:free",
        )
        object.__setattr__(sel, "is_free", False)

        decision = check_model_policy(sel, source=SelectionSource.EXPLICIT)
        assert decision.is_blocked
        assert decision.reason == "openrouter_free_blocked"

        with pytest.raises(OpenRouterFreeBlocked):
            enforce_model_policy(sel, source=SelectionSource.EXPLICIT)

    def test_dataclass_with_malformed_tokens_rejected(self):
        # Caller tự dựng ModelSelector với model chứa injection / ký tự shell
        bad_selectors = [
            ModelSelector(raw="bad", model="deepseek;rm -rf /"),
            ModelSelector(raw="bad", model="-leading-dash"),
            ModelSelector(raw="bad", model="model-"),
            ModelSelector(raw="bad", model=".."),
            ModelSelector(raw="bad", model=".hidden"),
            ModelSelector(raw="bad", model="model."),
            ModelSelector(raw="bad", provider="bad_provider!", model="valid-model"),
            ModelSelector(raw="bad", model="valid-model", variant="invalid_variant"),
            ModelSelector(raw="bad\0null", model="valid-model"),
            ModelSelector(raw="bad-🚀", model="valid-model"),
            ModelSelector(raw="bad", model=":free"),  # :free mà không có openrouter provider
        ]
        for bad_sel in bad_selectors:
            decision = check_model_policy(bad_sel)
            assert decision.is_blocked
            assert decision.reason == "malformed_selector"

            with pytest.raises(MalformedSelectorError):
                enforce_model_policy(bad_sel)


# ===========================================================================
# 10. Provider Conflict Policy (Negative Tests)
# ===========================================================================

class TestProviderConflictPolicy:
    def test_parse_conflicting_explicit_provider(self):
        with pytest.raises(ConflictingProviderError) as exc_info:
            parse_model_selector(
                "opencode-go/deepseek-v4.1-flash",
                explicit_provider="openrouter",
            )
        assert exc_info.value.reason == "conflicting_provider"
        assert exc_info.value.provider == "openrouter"

    def test_parse_conflicting_openrouter_provider(self):
        with pytest.raises(ConflictingProviderError):
            parse_model_selector(
                "openrouter/minimax/minimax-m3",
                explicit_provider="opencode-go",
            )

    def test_check_policy_conflicting_provider_string_selector(self):
        decision = check_model_policy(
            "opencode-go/deepseek-v4.1-flash",
            provider="openrouter",
        )
        assert decision.is_blocked
        assert decision.reason == "conflicting_provider"
        assert any("Conflicting provider" in w for w in decision.warnings)

        with pytest.raises(ConflictingProviderError) as exc_info:
            enforce_model_policy(
                "opencode-go/deepseek-v4.1-flash",
                provider="openrouter",
            )
        assert exc_info.value.reason == "conflicting_provider"
        assert exc_info.value.provider == "openrouter"

    def test_check_policy_conflicting_provider_value_object(self):
        sel = ModelSelector(
            raw="opencode-go/deepseek-v4.1-flash",
            provider="opencode-go",
            model="deepseek-v4.1-flash",
        )
        decision = check_model_policy(sel, provider="openrouter")
        assert decision.is_blocked
        assert decision.reason == "conflicting_provider"

        with pytest.raises(ConflictingProviderError) as exc_info:
            enforce_model_policy(sel, provider="openrouter")
        assert exc_info.value.reason == "conflicting_provider"
        assert exc_info.value.provider == "openrouter"

    def test_matching_explicit_provider_allowed(self):
        # Trùng khớp provider (kể cả khác casing / whitespace quanh provider) -> Cho phép
        decision = check_model_policy(
            "opencode-go/deepseek-v4.1-flash",
            provider="  OpEnCoDe-Go  ",
        )
        assert decision.is_allowed


# ===========================================================================
# 11. Invalid Source Fail-Closed Policy (Negative Tests)
# ===========================================================================

class TestInvalidSourcePolicy:
    @pytest.mark.parametrize("invalid_source", [
        "magic",
        "unknown",
        "random",
        "",
        "   ",
        "implicit",
        "fallback",
        "DEFAULT_TYPO",
        "auto_detect",
        12345,
        None,
        True,
        False,
    ])
    def test_invalid_source_fail_closed_string_selector(self, invalid_source):
        decision = check_model_policy(
            "deepseek-v4.1-flash",
            source=invalid_source,
        )
        assert decision.is_blocked
        assert decision.reason == "invalid_source"

        with pytest.raises(InvalidSourceError) as exc_info:
            enforce_model_policy(
                "deepseek-v4.1-flash",
                source=invalid_source,
            )
        assert exc_info.value.reason == "invalid_source"
        assert exc_info.value.source == str(invalid_source)

    def test_invalid_source_fail_closed_value_object(self):
        sel = ModelSelector(raw="deepseek-v4.1-flash", model="deepseek-v4.1-flash")
        decision = check_model_policy(sel, source="unrecognized_source")
        assert decision.is_blocked
        assert decision.reason == "invalid_source"

        with pytest.raises(InvalidSourceError):
            enforce_model_policy(sel, source="unrecognized_source")

    def test_valid_sources_accepted(self):
        # Các nguồn hợp lệ được chấp nhận
        for src in VALID_SOURCES:
            decision = check_model_policy("deepseek-v4.1-flash", source=src)
            assert decision.is_allowed


# ===========================================================================
# 12. Strict Token Grammar Policy (Negative Tests)
# ===========================================================================

class TestTokenGrammarPolicy:
    @pytest.mark.parametrize("shell_injection", [
        "model;rm -rf /",
        "model&echo test",
        "model|cat /etc/passwd",
        "$(whoami)",
        "`id`",
        "model>out",
        "model<in",
        "model*test",
        "model?test",
        "model~backup",
        "model#comment",
        "model!bang",
        "model{a,b}",
        "model(1)",
        "model\"quote",
        "model'quote",
        "model\\escape",
    ])
    def test_reject_shell_and_punctuation_injection(self, shell_injection):
        with pytest.raises(MalformedSelectorError):
            parse_model_selector(shell_injection)

        decision = check_model_policy(shell_injection)
        assert decision.is_blocked
        assert decision.reason == "malformed_selector"

    @pytest.mark.parametrize("unicode_input", [
        "deepseek-🚀",
        "dеерsееk",       # Cyrillic 'е' and 'р' homoglyphs
        "ｄｅｅｐｓｅｅｋ",     # Full-width
        "münchen-model",
        "tiếng-việt",
        "modelo-español",
    ])
    def test_reject_non_ascii_and_unicode_homoglyphs(self, unicode_input):
        with pytest.raises(MalformedSelectorError):
            parse_model_selector(unicode_input)

        decision = check_model_policy(unicode_input)
        assert decision.is_blocked
        assert decision.reason == "malformed_selector"

    @pytest.mark.parametrize("leading_dash", [
        "-model",
        "--model",
        "-flag",
        "provider/-model",
        "-provider/model",
        "opencode-go/-deepseek-v4.1-flash",
    ])
    def test_reject_leading_dash(self, leading_dash):
        with pytest.raises(MalformedSelectorError):
            parse_model_selector(leading_dash)

        decision = check_model_policy(leading_dash)
        assert decision.is_blocked
        assert decision.reason == "malformed_selector"

    @pytest.mark.parametrize("trailing_dash", [
        "model-",
        "provider-/model",
        "opencode-go/deepseek-v4.1-flash-",
    ])
    def test_reject_trailing_dash(self, trailing_dash):
        with pytest.raises(MalformedSelectorError):
            parse_model_selector(trailing_dash)

        decision = check_model_policy(trailing_dash)
        assert decision.is_blocked
        assert decision.reason == "malformed_selector"

    @pytest.mark.parametrize("path_traversal", [
        ".",
        "..",
        ".../model",
        "provider/..",
        "../model",
        "provider/../model",
        ".hidden-model",
        "model.",
        "provider./model",
    ])
    def test_reject_path_traversal_and_dot_anomalies(self, path_traversal):
        with pytest.raises(MalformedSelectorError):
            parse_model_selector(path_traversal)

        decision = check_model_policy(path_traversal)
        assert decision.is_blocked
        assert decision.reason == "malformed_selector"

    def test_no_normalization_of_invalid_tokens(self):
        # Không được tự tiện strip ký tự sai để biến thành hợp lệ
        # Ví dụ: "-deepseek-v4.1-flash" không được cắt dash thành "deepseek-v4.1-flash"
        with pytest.raises(MalformedSelectorError):
            parse_model_selector("-deepseek-v4.1-flash")

        with pytest.raises(MalformedSelectorError):
            parse_model_selector("deep;seek-v4.1-flash")

    def test_reject_bare_colon_free_without_openrouter(self):
        # :free không có provider openrouter phải bị từ chối
        with pytest.raises(MalformedSelectorError):
            parse_model_selector(":free")
