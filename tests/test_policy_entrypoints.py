"""Integration tests for model policy and security entrypoints (Lô 4 + 9).

Covers:
1. CLI entrypoints (bin/dispatch.py):
   - Whitelist replaced with unified resolver
   - Positional vs --model conflict blocked
   - Go flags (--profile, --provider)
   - Early vision gate: real/unknown attachments blocked before prompt-file read/attachment stat/probe
   - Sensitive vision without trusted single-turn confirmation blocked
   - Contributor/free implicit blocked, --allow-unknown does not bypass policy
   - OpenRouter :free / unresolved router blocked
   - Gemini auto preserved without inventing concrete model
   - Full DispatchResult JSON on blocked

2. Library / API entrypoints (bin/lib/dispatcher.py: run_vendor):
   - Policy evaluated before probe/spawn/network
   - Original source (auto/default/failover) preserved
   - Go adapters failclosed sandbox_unsupported BEFORE detector
   - Dedicated Go branch (no dynamic shell fallback)
   - Vision gate integration and no arbitrary string consent
   - Retry/failover do not inherit consent
   - agy auto does not arbitrarily pick catalog[0]
   - Claude ToS bounded options preserved

3. Direct or_dispatch entrypoints (bin/lib/openrouter.py):
   - Policy checked before key/opener/network
   - :free, auto, unresolved router blocked
   - Contributor models blocked
   - Valid paid models pass policy to opener

4. Builder entrypoints (bin/lib/dispatch_core.py):
   - Builders enforce policy before argv building / file writing
   - Go builders fail-closed with sandbox_unsupported

5. Shared resolver (lib.dispatcher.resolve_dispatch_target):
   - CLI and library share ONE decision path
   - original source (auto/default/failover) never becomes explicit on resolve
   - OpenRouter org/model namespace preserved behind openrouter/ prefix
   - Gemini auto stays literal 'auto' (no invented slug)

6. OpenRouter direct API ordering: policy -> effort -> key -> opener, and
   requested_model vs served_model are never conflated.

7. CLI spies (in-process dispatch.main): contributor / free default / sensitive
   vision blocked with NO run_vendor call, NO subprocess spawn, NO network, and
   no prompt-file/attachment read.

Strictly zero personal keys/configs and spy assertions demonstrating NO probe/spawn/network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bin.lib.dispatch_core import (
    DispatchContributorBlocked,
    DispatchError,
    DispatchFreeBlocked,
    DispatchPolicyViolation,
    DispatchResult,
    build_agy_cmd,
    build_claude_cmd,
    build_codex_cmd,
    build_dsh_cmd,
    build_grok_cmd,
    build_hermes_cmd,
    build_opencode_cmd,
    write_dsh_patch,
)
from bin.lib.dispatcher import run_vendor
from bin.lib.model_policy import (
    GO_VENDORS,
    ContributorModelBlocked,
    FreeModelBlocked,
    MalformedSelectorError,
    SelectionSource,
    UnapprovedProfileError,
    UnapprovedProviderError,
    UnresolvedDestinationError,
)
from bin.lib.openrouter import ORResult, or_dispatch
from bin.lib.states import VendorProbe, VendorState
from bin.lib.vision import SingleTurnConfirmation, VisionBlockedError


# ---------------------------------------------------------------------------
# Helpers & Spies
# ---------------------------------------------------------------------------

class SpyDetector:
    def __init__(self):
        self.called = False
        self.call_count = 0
        self.last_spec = None

    def __call__(self, spec):
        self.called = True
        self.call_count += 1
        self.last_spec = spec
        return VendorProbe(name=spec.name, path="/bin/fake", authed=True, quota_capped=False)


class SpyRunner:
    def __init__(self, stdout="ok", stderr="", returncode=0):
        self.called = False
        self.call_count = 0
        self.last_cmd = None
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode

    def __call__(self, cmd, **kwargs):
        self.called = True
        self.call_count += 1
        self.last_cmd = cmd

        class _Res:
            pass

        r = _Res()
        r.stdout = self.stdout
        r.stderr = self.stderr
        r.returncode = self.returncode
        return r


class SpyOpener:
    def __init__(self, response_bytes=b'{"choices":[{"message":{"content":"ok"}}]}'):
        self.called = False
        self.call_count = 0
        self.last_req = None
        self.response_bytes = response_bytes

    def __call__(self, req, timeout=120):
        self.called = True
        self.call_count += 1
        self.last_req = req

        class _Resp:
            def __init__(self, data):
                self.data = data
            def read(self):
                return self.data

        return _Resp(self.response_bytes)


# ---------------------------------------------------------------------------
# 1. Library entrypoint (run_vendor) tests
# ---------------------------------------------------------------------------

def test_run_vendor_contributor_blocked_before_detector_and_runner():
    """Contributor model must be blocked before detector probe or runner execution."""
    spy_det = SpyDetector()
    spy_run = SpyRunner()

    res = run_vendor(
        vendor="codex",
        prompt="hello world",
        model="gpt-6.1-sol-contributor",
        runner=spy_run,
        detector=spy_det,
    )

    assert res.status == "blocked"
    assert res.reason == "contributor_model_blocked"
    assert not spy_det.called, "Detector probe was called on blocked contributor model"
    assert not spy_run.called, "Runner was called on blocked contributor model"


def test_run_vendor_free_model_implicit_blocked_before_detector():
    """Free model selected via auto/default must be blocked before probe or execution."""
    spy_det = SpyDetector()
    spy_run = SpyRunner()

    res = run_vendor(
        vendor="opencode",
        prompt="hello",
        model="deepseek-v4.1-flash-free",
        source="auto",
        runner=spy_run,
        detector=spy_det,
    )

    assert res.status == "blocked"
    assert res.reason == "free_model_not_explicit"
    assert not spy_det.called, "Detector was invoked on implicit free model"
    assert not spy_run.called, "Runner was invoked on implicit free model"


def test_run_vendor_free_model_explicit_passes_policy_to_sandbox_check():
    """Free model selected explicitly (--model ...-free) passes policy check, then fails on sandbox."""
    spy_det = SpyDetector()
    spy_run = SpyRunner()

    res = run_vendor(
        vendor="opencode",
        prompt="hello",
        model="deepseek-v4.1-flash-free",
        source="explicit",
        runner=spy_run,
        detector=spy_det,
    )

    # Policy allowed explicit free, then Go adapter failclosed on sandbox_unsupported
    assert res.status == "blocked"
    assert res.reason == "sandbox_unsupported"
    assert not spy_det.called, "Detector probe was called for unverified Go adapter"
    assert not spy_run.called, "Runner was called for unverified Go adapter"


def test_run_vendor_go_adapters_failclosed_sandbox_unsupported_before_detector():
    """Go adapters (opencode, hermes) failclosed with sandbox_unsupported BEFORE detector."""
    for go_vendor in ("opencode", "hermes"):
        spy_det = SpyDetector()
        spy_run = SpyRunner()

        res = run_vendor(
            vendor=go_vendor,
            prompt="test task",
            model="auto",
            runner=spy_run,
            detector=spy_det,
        )

        assert res.status == "blocked"
        assert res.reason == "sandbox_unsupported"
        assert "no proven sandbox isolation" in res.warnings[0]
        assert not spy_det.called, f"Detector was invoked for Go adapter {go_vendor}"
        assert not spy_run.called, f"Runner was invoked for Go adapter {go_vendor}"


def test_run_vendor_vision_real_attachments_blocked_before_detector():
    """Attachments without synthetic_vision=True must be blocked before detector or runner."""
    spy_det = SpyDetector()
    spy_run = SpyRunner()

    res = run_vendor(
        vendor="codex",
        prompt="examine attachment",
        model="auto",
        attachments=["/nonexistent/real_scan.pdf"],
        synthetic_vision=False,
        runner=spy_run,
        detector=spy_det,
    )

    assert res.status == "blocked"
    assert res.reason == "vision_blocked"
    assert not spy_det.called, "Detector was invoked on real vision attachment"
    assert not spy_run.called, "Runner was invoked on real vision attachment"


def test_run_vendor_vision_synthetic_blocked_for_unverified_adapter():
    """Synthetic vision attachments for unverified adapters are honestly blocked."""
    spy_det = SpyDetector()
    spy_run = SpyRunner()

    res = run_vendor(
        vendor="codex",
        prompt="examine synthetic",
        model="auto",
        attachments=["/nonexistent/test.png"],
        synthetic_vision=True,
        runner=spy_run,
        detector=spy_det,
    )

    assert res.status == "blocked"
    assert res.reason == "vision_blocked"
    assert not spy_det.called
    assert not spy_run.called


def test_run_vendor_sensitive_vision_string_consent_rejected():
    """Arbitrary string consent for sensitive vision is strictly rejected."""
    spy_det = SpyDetector()
    spy_run = SpyRunner()

    res = run_vendor(
        vendor="codex",
        prompt="examine scan",
        model="auto",
        attachments=["/nonexistent/doc.pdf"],
        allow_sensitive_vision=True,
        sensitive_confirmation="I confirm Tuan approved this",
        runner=spy_run,
        detector=spy_det,
    )

    assert res.status == "blocked"
    assert res.reason == "vision_blocked"
    assert not spy_det.called
    assert not spy_run.called


def test_run_vendor_sensitive_confirmation_no_retry_failover_inheritance():
    """Confirmation object rejects inherited consent on retry or failover."""
    conf = SingleTurnConfirmation(
        token="tok1",
        exact_files=("/tmp/a.png",),
        exact_model="deepseek-v4.1-flash",
        exact_provider="opencode-go",
        is_trusted_ui=True,
    )

    # Valid check
    valid, reason = conf.is_valid_for(
        files=["/tmp/a.png"],
        model="deepseek-v4.1-flash",
        provider="opencode-go",
        is_retry=False,
        is_failover=False,
    )
    assert valid is True

    # Retry inheritance rejected
    valid_retry, reason_retry = conf.is_valid_for(
        files=["/tmp/a.png"],
        model="deepseek-v4.1-flash",
        provider="opencode-go",
        is_retry=True,
    )
    assert valid_retry is False
    assert "retry or failover" in reason_retry

    # Failover inheritance rejected
    valid_fo, reason_fo = conf.is_valid_for(
        files=["/tmp/a.png"],
        model="deepseek-v4.1-flash",
        provider="opencode-go",
        is_failover=True,
    )
    assert valid_fo is False


def test_run_vendor_gemini_auto_preserved_no_invented_model():
    """Gemini auto must be preserved without inventing a default model slug."""
    spy_run = SpyRunner(stdout="gemini response")
    env = os.environ.copy()

    # Route should run _dispatch_gemini with model='auto'
    res = run_vendor(
        vendor="gemini",
        prompt="ping",
        model="auto",
        runner=spy_run,
    )
    assert res.status == "ok"
    assert res.model == "auto"
    assert res.served_model in ("agy:high", "gemini-3.5-flash")


def test_run_vendor_agy_auto_does_not_pick_catalog_zero():
    """agy auto fallback does not arbitrarily pick catalog[0]."""
    spy_run = SpyRunner(stdout="agy output")
    # Catalog contains arbitrary non-gemini model at index 0
    fake_catalog = ["some-random-unknown-model", "another-model"]

    probe = VendorProbe(
        name="agy",
        path="/bin/agy",
        authed=True,
        quota_capped=False,
        models=fake_catalog,
    )

    res = run_vendor(
        vendor="agy",
        prompt="ping",
        model="auto",
        runner=spy_run,
        detector=lambda spec: probe,
    )

    assert res.status == "ok"
    # Should use AGY_DEFAULT_MODEL ("gemini-3.8-flash-high"), NOT catalog[0]!
    assert res.served_model == "gemini-3.8-flash-high"
    assert spy_run.last_cmd is not None
    assert "some-random-unknown-model" not in spy_run.last_cmd
    assert "gemini-3.8-flash-high" in spy_run.last_cmd


def test_run_vendor_claude_bounded_flags_intact():
    """Claude invocation preserves all bounded ToS flags."""
    spy_run = SpyRunner(stdout="claude bounded ok")
    spy_det = SpyDetector()

    res = run_vendor(
        vendor="claude",
        prompt="bounded prompt",
        model="claude-opus-5",
        runner=spy_run,
        detector=spy_det,
    )

    assert res.status == "ok"
    assert spy_run.last_cmd is not None
    cmd = spy_run.last_cmd
    assert "--effort" in cmd and "low" in cmd
    assert "--permission-mode" in cmd and "plan" in cmd
    assert "--tools" in cmd
    assert "--no-session-persistence" in cmd
    assert "--disable-slash-commands" in cmd


# ---------------------------------------------------------------------------
# 2. Direct or_dispatch entrypoint tests
# ---------------------------------------------------------------------------

def test_or_dispatch_auto_unresolved_blocked_without_network():
    """Direct or_dispatch with model='auto' is blocked before key check or network."""
    spy_opener = SpyOpener()

    res = or_dispatch("hello", model="auto", key="dummy-key", opener=spy_opener)

    assert res.ok is False
    assert res.reason == "openrouter_unresolved_destination"
    assert not spy_opener.called, "Opener was called for unresolved OpenRouter router"


def test_or_dispatch_free_model_blocked_without_network():
    """Direct or_dispatch with a :free model is blocked before key check or network."""
    spy_opener = SpyOpener()

    res = or_dispatch("hello", model="minimax/minimax-m3:free", key="dummy-key", opener=spy_opener)

    assert res.ok is False
    assert res.reason == "openrouter_free_blocked"
    assert not spy_opener.called, "Opener was called for OpenRouter :free model"


def test_or_dispatch_contributor_blocked_without_network():
    """Direct or_dispatch with contributor model is blocked before key check or network."""
    spy_opener = SpyOpener()

    res = or_dispatch("hello", model="meta/llama-contributor", key="dummy-key", opener=spy_opener)

    assert res.ok is False
    assert res.reason == "contributor_model_blocked"
    assert not spy_opener.called, "Opener was called for contributor model"


def test_or_dispatch_valid_paid_model_reaches_key_and_opener():
    """Direct or_dispatch with valid paid model passes policy to opener."""
    spy_opener = SpyOpener(b'{"choices":[{"message":{"content":"response"}}],"model":"meta-llama/llama-3-8b-instruct"}')

    res = or_dispatch(
        prompt="hello",
        model="meta-llama/llama-3-8b-instruct",
        key="test-key-safe",
        opener=spy_opener,
    )

    assert res.ok is True
    assert res.text == "response"
    assert res.served_model == "meta-llama/llama-3-8b-instruct"
    assert spy_opener.called is True


# ---------------------------------------------------------------------------
# 3. Builder entrypoint tests
# ---------------------------------------------------------------------------

def test_builders_enforce_policy_on_contributor():
    """Builders block contributor models before building commands or writing files."""
    with pytest.raises(DispatchContributorBlocked):
        build_codex_cmd("gpt-6.1-sol-contributor", "read-only", None, "text")

    with pytest.raises(DispatchContributorBlocked):
        build_claude_cmd("claude-opus-contributor", "prompt")

    with pytest.raises(DispatchContributorBlocked):
        build_grok_cmd("grok-4.6-contributor", "read-only", None, "text", "/tmp/p")

    with pytest.raises(DispatchContributorBlocked):
        build_agy_cmd("gemini-3.8-flash-contributor", "prompt")

    with pytest.raises(DispatchContributorBlocked):
        build_dsh_cmd("deepseek-v4-pro-contributor", "/tmp/patch")

    with pytest.raises(DispatchContributorBlocked):
        write_dsh_patch("deepseek-v4-pro-contributor", "/tmp/patch")


def test_go_builders_failclosed_sandbox_unsupported():
    """Go builders raise DispatchError with reason sandbox_unsupported."""
    with pytest.raises(DispatchError) as exc_opencode:
        build_opencode_cmd("deepseek-v4.1-flash", "prompt", sandbox="read-only")
    assert exc_opencode.value.reason == "sandbox_unsupported"

    with pytest.raises(DispatchError) as exc_hermes:
        build_hermes_cmd("deepseek-v4.1-flash", "prompt", sandbox="read-only")
    assert exc_hermes.value.reason == "sandbox_unsupported"


# ---------------------------------------------------------------------------
# 4. CLI entrypoint (bin/dispatch.py) tests
# ---------------------------------------------------------------------------

def test_cli_positional_model_vs_model_flag_conflict_blocked():
    """CLI blocks when positional model conflicts with --model alias."""
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [
        sys.executable,
        str(repo_root / "bin" / "dispatch.py"),
        "codex",
        "gpt-6.1-sol",
        "--model",
        "gpt-5.5",
        "--prompt",
        "hello",
        "--result-json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 2

    data = json.loads(proc.stdout)
    assert data["status"] == "blocked"
    assert "conflicting positional model" in data["summary"]


def test_cli_contributor_model_blocked_with_result_json():
    """CLI blocks contributor model with full result JSON and proper reason."""
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [
        sys.executable,
        str(repo_root / "bin" / "dispatch.py"),
        "codex",
        "gpt-6.1-sol-contributor",
        "--prompt",
        "hello",
        "--result-json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 2

    data = json.loads(proc.stdout)
    assert data["status"] == "blocked"
    assert data["reason"] == "contributor_model_blocked"
    assert "Contributor models" in data["warnings"][0]


def test_cli_allow_unknown_model_does_not_bypass_contributor_block():
    """CLI --allow-unknown-model does not bypass contributor model policy."""
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [
        sys.executable,
        str(repo_root / "bin" / "dispatch.py"),
        "codex",
        "gpt-6.1-sol-contributor",
        "--allow-unknown-model",
        "--prompt",
        "hello",
        "--result-json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 2

    data = json.loads(proc.stdout)
    assert data["status"] == "blocked"
    assert data["reason"] == "contributor_model_blocked"


def test_cli_vision_real_attachments_blocked_before_prompt_file_read():
    """CLI blocks real/unknown vision attachments BEFORE prompt-file read or attachment stat."""
    repo_root = Path(__file__).resolve().parents[1]
    # Non-existent prompt-file and non-existent attachment:
    # If early vision gate runs first, it must exit without trying to open prompt-file!
    cmd = [
        sys.executable,
        str(repo_root / "bin" / "dispatch.py"),
        "codex",
        "--file",
        "/nonexistent/doc_page.png",
        "--prompt-file",
        "/nonexistent/never_read_prompt.txt",
        "--result-json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 2

    data = json.loads(proc.stdout)
    assert data["status"] == "blocked"
    assert data["reason"] == "vision_blocked"
    assert "attachments real/unknown blocked" in data["summary"]
    # Verify that it didn't fail on missing prompt-file:
    assert "không đọc được --prompt-file" not in proc.stderr
    assert "không đọc được --prompt-file" not in proc.stdout


def test_cli_vision_allow_sensitive_alone_blocked():
    """CLI with --allow-sensitive-vision alone without synthetic-vision is blocked."""
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [
        sys.executable,
        str(repo_root / "bin" / "dispatch.py"),
        "codex",
        "--file",
        "/nonexistent/doc_page.png",
        "--allow-sensitive-vision",
        "--prompt",
        "examine",
        "--result-json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 2

    data = json.loads(proc.stdout)
    assert data["status"] == "blocked"
    assert data["reason"] == "vision_blocked"


def test_cli_openrouter_auto_blocked():
    """CLI with openrouter vendor and model 'auto' is blocked by policy."""
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [
        sys.executable,
        str(repo_root / "bin" / "dispatch.py"),
        "openrouter",
        "auto",
        "--prompt",
        "hello",
        "--result-json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 2

    data = json.loads(proc.stdout)
    assert data["status"] == "blocked"
    assert data["reason"] == "openrouter_unresolved_destination"


def test_cli_dump_config_resolves_profile_and_provider():
    """CLI --dump-config resolves Go profile and provider properly without dispatching."""
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [
        sys.executable,
        str(repo_root / "bin" / "dispatch.py"),
        "opencode",
        "--profile",
        "glm-5.3-flash",
        "--dump-config",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0

    data = json.loads(proc.stdout)
    assert data["vendor"] == "opencode"
    assert data["resolved_model"] == "glm-5.3-flash"
    assert data["effort"] == "max"
    assert data["provider"] == "opencode-go"
    assert data["profile"] == "glm-5.3-flash"


# ---------------------------------------------------------------------------
# 5. Shared resolver invariants (CLI == library, source preserved, OR scoping)
# ---------------------------------------------------------------------------

def test_resolve_dispatch_target_preserves_original_source():
    """source gốc auto/default/failover không bị hoá thành explicit sau resolve."""
    from lib.dispatcher import resolve_dispatch_target

    auto = resolve_dispatch_target(vendor="codex", model="auto", source="explicit")
    assert auto.model == "gpt-6.1-sol"
    assert auto.source == "auto", "auto + explicit-intent phải giữ nguyên là auto"

    auto_explicit_source = resolve_dispatch_target(vendor="codex", model="auto", source=SelectionSource.AUTO)
    assert auto_explicit_source.source == "auto"

    default = resolve_dispatch_target(vendor="codex", model="auto", source="default")
    assert default.source == "default", "default không được nâng thành explicit"

    failover = resolve_dispatch_target(vendor="codex", model="auto", source="failover")
    assert failover.source == "failover", "failover không được nâng thành explicit"

    explicit = resolve_dispatch_target(vendor="codex", model="gpt-6.1-sol", source="explicit")
    assert explicit.source == "explicit"


def test_resolve_dispatch_target_free_model_blocked_for_non_explicit_source():
    """Free model ở nguồn default/failover bị chặn trước mọi I/O."""
    from lib.dispatcher import resolve_dispatch_target
    from lib.model_policy import FreeModelBlocked

    for src in ("default", "failover"):
        with pytest.raises(FreeModelBlocked):
            resolve_dispatch_target(vendor="codex", model="gpt-6.1-sol-free", source=src)


def test_resolve_dispatch_target_openrouter_keeps_org_model_namespace():
    """org/model của OpenRouter không bị hiểu thành provider khác."""
    from lib.dispatcher import resolve_dispatch_target

    t = resolve_dispatch_target(
        vendor="openrouter",
        model="meta-llama/llama-3-8b-instruct",
        provider="openrouter",
        source="explicit",
    )
    assert t.provider == "openrouter"
    assert t.model == "meta-llama/llama-3-8b-instruct"

    # router generic / :free vẫn bị chặn dù có prefix org/model
    from lib.model_policy import OpenRouterFreeBlocked, UnresolvedDestinationError

    with pytest.raises(UnresolvedDestinationError):
        resolve_dispatch_target(vendor="openrouter", model="auto", provider="openrouter")
    with pytest.raises(OpenRouterFreeBlocked):
        resolve_dispatch_target(
            vendor="openrouter", model="minimax/minimax-m3:free", provider="openrouter"
        )


def test_resolve_dispatch_target_gemini_auto_is_not_invented():
    """Gemini auto: giữ literal 'auto' + warning, không bịa slug mặc định."""
    from lib.dispatcher import resolve_dispatch_target

    t = resolve_dispatch_target(vendor="gemini", model="auto", source="explicit")
    assert t.model == "auto"
    assert t.selector is None
    assert any("gemini auto" in w for w in t.warnings)


def test_run_vendor_policy_warning_reaches_result_json():
    """Warning của resolver (vd gemini auto) phải xuống result.warnings (P4)."""
    spy_run = SpyRunner(stdout="gemini ok")

    res = run_vendor(vendor="gemini", prompt="ping", model="auto", runner=spy_run)
    assert res.status == "ok"
    assert any("gemini auto" in w for w in res.warnings), res.warnings


def test_run_vendor_agy_served_model_marked_as_intent():
    """agy auto: served_model chỉ là slug ĐÃ GỬI và phải nói rõ đó là intent."""
    from lib.dispatch_core import AGY_DEFAULT_MODEL

    spy_run = SpyRunner(stdout="agy output")
    probe = VendorProbe(name="agy", path="/bin/agy", authed=True, quota_capped=False,
                        models=[AGY_DEFAULT_MODEL])

    res = run_vendor(vendor="agy", prompt="ping", model="auto", runner=spy_run,
                     detector=lambda spec: probe)
    assert res.status == "ok"
    assert res.model == "auto", "result.model là REQUESTED, không phải slug đã ghim"
    assert res.served_model == AGY_DEFAULT_MODEL
    assert any("intent" in w for w in res.warnings), res.warnings


def test_run_vendor_go_never_spawns_even_if_confinement_flag_flipped():
    """Go adapter: kể cả khi hằng số confinement bị lật, builder fail-closed vẫn
    chặn spawn — không có lượt chạy giả."""
    import lib.dispatcher as disp_mod
    from lib.dispatcher import _dispatch_go_adapter, GO_SANDBOX_CONFINED

    assert GO_SANDBOX_CONFINED is False, "chưa có evidence confinement trong repo"

    spy = SpyRunner()
    res = _dispatch_go_adapter(
        vendor="opencode",
        prompt="hi",
        model="deepseek-v4.1-flash",
        effort="high",
        attachments=None,
        sandbox="read-only",
        workdir=None,
        source="explicit",
        timeout=10,
        env={},
        runner=spy,
    )
    assert res.status == "blocked"
    assert res.reason == "sandbox_unsupported"
    assert spy.called is False, "builder fail-closed phải chặn trước spawn"

    # Lật hằng số nội bộ (mô phỏng tương lai có confinement) → vẫn blocked bởi builder
    orig = disp_mod.GO_SANDBOX_CONFINED
    try:
        disp_mod.GO_SANDBOX_CONFINED = True
        spy2 = SpyRunner()
        det = SpyDetector()
        res2 = disp_mod.run_vendor(
            vendor="hermes", prompt="hi", model="auto", runner=spy2, detector=det
        )
        assert res2.status == "blocked"
        assert res2.reason == "sandbox_unsupported"
        assert spy2.called is False, "không được giả chạy khi builder còn fail-closed"
    finally:
        disp_mod.GO_SANDBOX_CONFINED = orig


def test_run_vendor_go_block_lists_requested_and_agentic_facts():
    """Result blocked của Go phải nêu reason + requested/provider/effort/source."""
    spy_det = SpyDetector()
    spy_run = SpyRunner()

    res = run_vendor(vendor="opencode", prompt="hi", model="auto",
                     runner=spy_run, detector=spy_det)
    assert res.status == "blocked"
    assert res.reason == "sandbox_unsupported"
    joined = "\n".join(res.warnings)
    assert "sandbox_unsupported" in joined
    assert "KHÔNG probe" in joined
    assert "deepseek-v4.1-flash" in joined
    assert "opencode-go" in joined
    assert not spy_det.called and not spy_run.called


# ---------------------------------------------------------------------------
# 6. OpenRouter direct API: policy-first ordering & requested/served split
# ---------------------------------------------------------------------------

def test_or_dispatch_invalid_effort_checked_before_key_lookup(monkeypatch):
    """Effort sai phải trả lỗi TRƯỚC khi đọc key (không I/O vô ích)."""
    import lib.openrouter as oro

    def _boom(*a, **k):
        raise AssertionError("get_or_key must not be called for invalid effort")

    monkeypatch.setattr(oro, "get_or_key", _boom)
    spy_opener = SpyOpener()

    res = oro.or_dispatch("hi", model="meta-llama/llama-3-8b-instruct",
                          effort="ultra-mega", opener=spy_opener)
    assert res.ok is False
    assert res.reason == "invalid_effort"
    assert not spy_opener.called


def test_or_dispatch_default_source_free_model_blocked_without_key_or_network():
    """source=default + :free bị chặn trước key/network (không kế thừa explicit)."""
    spy_opener = SpyOpener()

    res = or_dispatch("hi", model="minimax/minimax-m3:free", source="default",
                      key="dummy", opener=spy_opener)
    assert res.ok is False
    assert res.reason in ("openrouter_free_blocked", "free_model_not_explicit")
    assert not spy_opener.called


def test_or_dispatch_requested_and_served_are_distinct():
    """served_model chỉ lấy từ response; requested_model giữ slug đã yêu cầu."""
    spy_opener = SpyOpener(
        b'{"choices":[{"message":{"content":"ok"}}],"model":"anthropic/claude-opus-5"}'
    )

    res = or_dispatch("hi", model="meta-llama/llama-3-8b-instruct",
                      key="dummy", opener=spy_opener)
    assert res.ok is True
    assert res.requested_model == "meta-llama/llama-3-8b-instruct"
    assert res.served_model == "anthropic/claude-opus-5"
    assert res.served_model != res.requested_model


def test_or_dispatch_bad_response_is_explicit_error():
    """Response thiếu choices không được nổ exception thô hay giả success."""
    spy_opener = SpyOpener(b'{"unexpected":true}')

    res = or_dispatch("hi", model="meta-llama/llama-3-8b-instruct",
                      key="dummy", opener=spy_opener)
    assert res.ok is False
    assert res.reason == "bad_response"
    assert res.served_model is None


# ---------------------------------------------------------------------------
# 7. CLI spies: policy-gate chặn TRƯỚC run_vendor/spawn/network
# ---------------------------------------------------------------------------

class _CliSpy:
    """Ghi lại mọi nỗ lực spawn/network trong tiến trình CLI."""

    def __init__(self, monkeypatch):
        self.spawned = []
        self.networked = []
        import bin.dispatch as cli
        self.cli = cli
        self.lib_called = []

        def _spawn(*a, **k):
            self.spawned.append((a, k))
            raise AssertionError("CLI spawned a subprocess on a blocked request")

        def _net(*a, **k):
            self.networked.append((a, k))
            raise AssertionError("CLI hit the network on a blocked request")

        import urllib.request as _urlreq
        monkeypatch.setattr(cli.subprocess, "run", _spawn)
        monkeypatch.setattr(_urlreq, "urlopen", _net)
        monkeypatch.setattr(cli, "run_vendor", lambda *a, **k: self.lib_called.append(k))

    def run(self, argv):
        import sys as _sys
        cli = self.cli
        old = _sys.argv
        _sys.argv = ["dispatch.py"] + argv
        try:
            with pytest.raises(SystemExit) as exc:
                cli.main()
        finally:
            _sys.argv = old
        return exc.value.code


def _run_cli_spy(monkeypatch, capsys, argv):
    spy = _CliSpy(monkeypatch)
    code = spy.run(argv)
    out, err = capsys.readouterr()
    return spy, code, out, err


def test_cli_spy_contributor_blocks_without_spawn_or_network(monkeypatch, capsys):
    spy, code, out, err = _run_cli_spy(
        monkeypatch, capsys,
        ["codex", "gpt-6.1-sol-contributor", "--prompt", "hi", "--result-json"],
    )
    assert code == 2
    assert spy.spawned == [] and spy.networked == []
    assert spy.lib_called == [], "policy phải chặn trước cả run_vendor"
    data = json.loads(out)
    assert data["status"] == "blocked"
    assert data["reason"] == "contributor_model_blocked"
    assert data["served_model"] is None


def test_cli_spy_free_default_blocks_without_spawn(monkeypatch, capsys):
    """Config default là model free ⇒ auto bị chặn, không spawn, không probe."""
    spy = _CliSpy(monkeypatch)

    fake_cfg = {
        "schema_version": 3,
        "vendors": {
            "codex": {
                "default_model": "gpt-6.1-sol-free",
                "default_effort": "low",
                "models": None,
            }
        },
    }
    monkeypatch.setattr(spy.cli, "load_vendor_config", lambda *a, **k: fake_cfg)

    code = spy.run(["codex", "--prompt", "hi", "--result-json"])
    out, _err = capsys.readouterr()

    assert code == 2
    assert spy.spawned == [] and spy.networked == [] and spy.lib_called == []
    data = json.loads(out)
    assert data["status"] == "blocked"
    assert data["reason"] == "free_model_not_explicit"


def test_cli_spy_sensitive_vision_blocks_without_spawn_or_file_io(monkeypatch, capsys):
    spy = _CliSpy(monkeypatch)

    read_calls = []
    import pathlib as _pathlib
    orig_read_text = _pathlib.Path.read_text
    orig_stat = _pathlib.Path.stat

    def _read(self, *a, **k):
        read_calls.append(("read_text", str(self)))
        return orig_read_text(self, *a, **k)

    def _stat(self, *a, **k):
        read_calls.append(("stat", str(self)))
        return orig_stat(self, *a, **k)

    monkeypatch.setattr(_pathlib.Path, "read_text", _read)
    monkeypatch.setattr(_pathlib.Path, "stat", _stat)

    code = spy.run([
        "codex",
        "--file", "/nonexistent/real_scan.png",
        "--prompt-file", "/nonexistent/prompt.txt",
        "--result-json",
    ])
    out, _err = capsys.readouterr()

    assert code == 2
    assert spy.spawned == [] and spy.networked == [] and spy.lib_called == []
    data = json.loads(out)
    assert data["reason"] == "vision_blocked"
    blocked_reads = [c for c in read_calls if c[1].startswith("/nonexistent")]
    assert blocked_reads == [], f"attachments/prompt phải chưa bị đọc/stat: {blocked_reads}"


def test_cli_spy_allow_unknown_still_blocks_contributor(monkeypatch, capsys):
    spy, code, out, _err = _run_cli_spy(
        monkeypatch, capsys,
        ["codex", "gpt-6.1-sol-contributor", "--allow-unknown-model",
         "--prompt", "hi", "--result-json"],
    )
    assert code == 2
    assert spy.spawned == [] and spy.networked == []
    assert json.loads(out)["reason"] == "contributor_model_blocked"


def test_cli_go_provider_conflict_blocked_without_lib_call(monkeypatch, capsys):
    """--provider sai cho Go bị chặn ở resolver, không gọi run_vendor."""
    spy, code, out, _err = _run_cli_spy(
        monkeypatch, capsys,
        ["opencode", "--provider", "openrouter", "--prompt", "hi", "--result-json"],
    )
    assert code == 2
    assert spy.lib_called == []
    data = json.loads(out)
    assert data["reason"] == "unapproved_go_provider"


def test_cli_openrouter_org_model_dump_config_keeps_namespace():
    """CLI openrouter org/model: provider không bị nhầm, dump-config exit 0."""
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, str(repo_root / "bin" / "dispatch.py"),
         "openrouter", "meta-llama/llama-3-8b-instruct", "--dump-config"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["provider"] == "openrouter"
    assert data["resolved_model"] == "meta-llama/llama-3-8b-instruct"
    assert data["requested_model"] == "meta-llama/llama-3-8b-instruct"


def test_cli_gemini_auto_dump_config_does_not_invent_model():
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, str(repo_root / "bin" / "dispatch.py"), "gemini", "--dump-config"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["resolved_model"] == "auto"
    assert data["source"] == "auto"
    assert data["default_model"] is None


def test_cli_model_flag_alias_alone_resolves():
    """--model alias một mình vẫn tương thích, positional vẫn chạy như cũ."""
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, str(repo_root / "bin" / "dispatch.py"),
         "codex", "--model", "gpt-6.1-sol", "--dump-config"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["requested_model"] == "gpt-6.1-sol"
    assert data["resolved_model"] == "gpt-6.1-sol"


# ---------------------------------------------------------------------------
# 8. Builder spies: không spawn/network/ghi file khi policy đã block
# ---------------------------------------------------------------------------

def test_builders_block_without_spawn_network_or_file_write(monkeypatch, tmp_path):
    import urllib.request as _urlreq

    spawns, nets = [], []

    def _spawn(*a, **k):
        spawns.append(a)
        raise AssertionError("builder must not spawn")

    def _net(*a, **k):
        nets.append(a)
        raise AssertionError("builder must not touch network")

    monkeypatch.setattr(subprocess, "run", _spawn)
    monkeypatch.setattr(_urlreq, "urlopen", _net)

    patch_path = tmp_path / "dsh-patch.yaml"

    with pytest.raises(DispatchContributorBlocked):
        build_codex_cmd("gpt-6.1-sol-contributor", "read-only", None, "text")
    with pytest.raises(DispatchContributorBlocked):
        write_dsh_patch("deepseek-v4-pro-contributor", str(patch_path))
    with pytest.raises(DispatchError):
        build_opencode_cmd("deepseek-v4.1-flash", "prompt", sandbox="read-only")

    assert spawns == [] and nets == []
    assert not patch_path.exists(), "builder bị block không được ghi file patch"
