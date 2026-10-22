"""Unit tests for Go builders (OpenCode & Hermes) and builder policy enforcement.

Lô 3:
- Builders opencode/hermes argv list:
  * absolute binary ~/.opencode/bin/opencode (Path.home)
  * hermes shutil.which absolute
  * model provider opencode-go
  * effort high / default GLM max
  * prompt Unicode/quote/multiline nguyên vẹn positional
  * attachment opencode -f chỉ cho synthetic validation
- Sandbox guard:
  * Hai Go builders bị BLOCKED với DispatchError reason 'sandbox_unsupported'
  * Không giả lập read-only an toàn giả tạo
  * Chặn mặc định cho đến khi có evidence sandbox
- Chốt chặn policy trên TẤT CẢ existing builders:
  * codex, claude, grok, agy, dsh/write_dsh_patch
  * Contributor cấm tuyệt đối (DispatchContributorBlocked)
  * Free model cấm implicit source (DispatchFreeBlocked)
  * write_dsh_patch chặn TRƯỚC KHI ghi file ra đĩa
  * Model unknown hợp lệ trên codex là advisory, không chặn
  * Claude bounded flags giữ nguyên
"""
from __future__ import annotations

import shutil
from pathlib import Path
import pytest

from lib.dispatch_core import (
    AGY_DEFAULT_MODEL,
    CLAUDE_DEFAULT_MODEL,
    CODEX_DEFAULT_MODEL,
    DSH_DEFAULT_MODEL,
    DispatchContributorBlocked,
    DispatchError,
    DispatchFreeBlocked,
    DispatchPolicyViolation,
    DispatchUnapprovedProfile,
    DispatchUnapprovedProvider,
    HERMES_DEFAULT_EFFORT,
    HERMES_DEFAULT_MODEL,
    OPENCODE_DEFAULT_EFFORT,
    OPENCODE_DEFAULT_MODEL,
    _build_hermes_argv,
    _build_opencode_argv,
    build_agy_cmd,
    build_claude_cmd,
    build_codex_cmd,
    build_dsh_cmd,
    build_grok_cmd,
    build_hermes_cmd,
    build_opencode_cmd,
    get_hermes_bin,
    get_opencode_bin,
    write_dsh_patch,
)
from lib.model_policy import (
    ContributorModelBlocked,
    FreeModelBlocked,
    ModelPolicyViolation,
)


# ===========================================================================
# 1. OpenCode Builder Tests
# ===========================================================================

class TestOpenCodeBuilder:
    def test_opencode_blocked_by_default_with_sandbox_unsupported(self):
        """Builder opencode phải bị BLOCKED mặc định với DispatchError reason sandbox_unsupported."""
        with pytest.raises(DispatchError) as exc_info:
            build_opencode_cmd("deepseek-v4.1-flash", "Kiểm tra prompt")
        assert exc_info.value.reason == "sandbox_unsupported"
        assert "sandbox_unsupported" in str(exc_info.value)
        assert "Plan mục 83" in str(exc_info.value)

    def test_opencode_does_not_pretend_read_only(self):
        """Dù truyền sandbox='read-only', opencode vẫn phải bị blocked thay vì giả lập an toàn."""
        with pytest.raises(DispatchError) as exc_info:
            build_opencode_cmd("deepseek-v4.1-flash", "Prompt", sandbox="read-only")
        assert exc_info.value.reason == "sandbox_unsupported"

    def test_opencode_pure_argv_helper_builds_valid_cmd(self):
        """Helper nội bộ pure private _build_opencode_argv trả về argv hợp lệ."""
        cmd = _build_opencode_argv("deepseek-v4.1-flash", "Nội dung task")
        assert isinstance(cmd, list)
        assert cmd[0] == get_opencode_bin()
        assert cmd[1:3] == ["run", "--model"]
        assert cmd[3] == "opencode-go/deepseek-v4.1-flash"
        assert cmd[4:6] == ["--variant", "high"]
        assert cmd[6] == "Nội dung task"

    def test_opencode_public_builder_no_evidence_sandbox_bypass(self):
        """Public builder build_opencode_cmd KHÔNG có tham số evidence_sandbox và luôn raise sandbox_unsupported."""
        import inspect
        sig = inspect.signature(build_opencode_cmd)
        assert "evidence_sandbox" not in sig.parameters

        # Caller không thể truyền evidence_sandbox (xoá cờ bypass)
        with pytest.raises(TypeError):
            build_opencode_cmd("deepseek-v4.1-flash", "Nội dung task", evidence_sandbox=True)  # type: ignore[call-arg]

        # Gọi thông thường luôn nổ sandbox_unsupported sau policy
        with pytest.raises(DispatchError) as exc_info:
            build_opencode_cmd("deepseek-v4.1-flash", "Nội dung task")
        assert exc_info.value.reason == "sandbox_unsupported"

    def test_opencode_normalize_slug_and_variant(self):
        """Chuẩn hoá slug và effort thật đưa vào argv thay vì truyền raw."""
        # 1. Truyền có provider prefix -> không bị lặp opencode-go/opencode-go/
        cmd1 = _build_opencode_argv("opencode-go/deepseek-v4.1-flash", "Prompt")
        assert cmd1[3] == "opencode-go/deepseek-v4.1-flash"
        assert cmd1[4:6] == ["--variant", "high"]

        # 2. Truyền selector kèm variant :high -> tách slug chuẩn và variant
        cmd2 = _build_opencode_argv("deepseek-v4.1-flash:high", "Prompt")
        assert cmd2[3] == "opencode-go/deepseek-v4.1-flash"
        assert cmd2[4:6] == ["--variant", "high"]

        # 3. Truyền variant :low -> override variant đúng
        cmd3 = _build_opencode_argv("deepseek-v4.1-flash:low", "Prompt")
        assert cmd3[3] == "opencode-go/deepseek-v4.1-flash"
        assert cmd3[4:6] == ["--variant", "low"]


    def test_opencode_absolute_binary(self):
        """Binary opencode phải là đường dẫn tuyệt đối ~/.opencode/bin/opencode (Path.home)."""
        bin_path = get_opencode_bin()
        expected = str(Path.home() / ".opencode/bin/opencode")
        assert bin_path == expected
        assert bin_path.startswith("/")

    def test_opencode_default_model_and_effort(self):
        """Model auto resolve thành deepseek-v4.1-flash với variant high."""
        cmd = _build_opencode_argv("auto", "Prompt")
        assert cmd[0] == get_opencode_bin()
        assert cmd[1:4] == ["run", "--model", "opencode-go/deepseek-v4.1-flash"]
        assert cmd[4:6] == ["--variant", "high"]
        assert cmd[6] == "Prompt"

    def test_opencode_glm_defaults_to_effort_max(self):
        """GLM-5.3-flash mặc định nhận effort max theo hồ sơ duyệt."""
        cmd = _build_opencode_argv("glm-5.3-flash", "Prompt")
        assert cmd[3] == "opencode-go/glm-5.3-flash"
        assert cmd[4:6] == ["--variant", "max"]

    def test_opencode_explicit_effort_override(self):
        """Caller truyền effort tường minh phải được tôn trọng."""
        cmd = _build_opencode_argv("deepseek-v4.1-flash", "Prompt", effort="medium")
        assert cmd[4:6] == ["--variant", "medium"]

    def test_opencode_prompt_unicode_quotes_multiline_intact(self):
        """Prompt Unicode, ngoặc kép, nháy đơn, xuống dòng phải giữ nguyên vẹn positional."""
        complex_prompt = (
            "Dòng 1: Tiếng Việt có dấu 'nháy đơn' và \"nháy kép\"\n"
            "Dòng 2: Ký tự đặc biệt: $PATH `whoami` \\n \t /dev/null\n"
            "Dòng 3: Emoji 🚀 & Đặng Xuân Khu\n"
        )
        cmd = _build_opencode_argv("deepseek-v4.1-flash", complex_prompt)
        assert cmd[-1] == complex_prompt

    def test_opencode_attachments_flag_f(self):
        """Cờ -f chỉ chèn cho attachments phục vụ validation vision sau."""
        files = ["/tmp/img1.png", "/tmp/doc.pdf"]
        cmd = _build_opencode_argv("deepseek-v4.1-flash", "Prompt", attachments=files)
        assert "-f" in cmd
        idx1 = cmd.index("-f")
        assert cmd[idx1 + 1] == "/tmp/img1.png"
        idx2 = cmd.index("-f", idx1 + 2)
        assert cmd[idx2 + 1] == "/tmp/doc.pdf"
        assert cmd[-1] == "Prompt"

    def test_opencode_pure_argv_helper_enforces_policy(self):
        """Helper pure argv _build_opencode_argv cũng không cho phép bypass policy."""
        with pytest.raises(DispatchContributorBlocked):
            _build_opencode_argv("opencode-go/deepseek-v4.1-flash-contributor", "Prompt")


# ===========================================================================
# 2. Hermes Builder Tests
# ===========================================================================

class TestHermesBuilder:
    def test_hermes_blocked_by_default_with_sandbox_unsupported(self):
        """Builder hermes phải bị BLOCKED mặc định với DispatchError reason sandbox_unsupported."""
        with pytest.raises(DispatchError) as exc_info:
            build_hermes_cmd("deepseek-v4.1-flash", "Kiểm tra prompt")
        assert exc_info.value.reason == "sandbox_unsupported"
        assert "sandbox_unsupported" in str(exc_info.value)

    def test_hermes_does_not_pretend_read_only(self):
        """Dù truyền sandbox='read-only', hermes vẫn phải bị blocked thay vì giả lập an toàn."""
        with pytest.raises(DispatchError) as exc_info:
            build_hermes_cmd("deepseek-v4.1-flash", "Prompt", sandbox="read-only")
        assert exc_info.value.reason == "sandbox_unsupported"

    def test_hermes_pure_argv_helper_builds_valid_cmd(self):
        """Helper nội bộ pure private _build_hermes_argv trả về argv hợp lệ."""
        cmd = _build_hermes_argv("deepseek-v4.1-flash", "Nội dung task")
        assert isinstance(cmd, list)
        assert cmd[0] == get_hermes_bin()
        assert cmd[1] == "-z"
        assert cmd[2] == "Nội dung task"
        assert cmd[3:5] == ["--provider", "opencode-go"]
        assert cmd[5:7] == ["-m", "deepseek-v4.1-flash"]
        assert cmd[7:9] == ["--reasoning", "high"]

    def test_hermes_public_builder_no_evidence_sandbox_bypass(self):
        """Public builder build_hermes_cmd KHÔNG có tham số evidence_sandbox và luôn raise sandbox_unsupported."""
        import inspect
        sig = inspect.signature(build_hermes_cmd)
        assert "evidence_sandbox" not in sig.parameters

        # Caller không thể truyền evidence_sandbox (xoá cờ bypass)
        with pytest.raises(TypeError):
            build_hermes_cmd("deepseek-v4.1-flash", "Nội dung task", evidence_sandbox=True)  # type: ignore[call-arg]

        # Gọi thông thường luôn nổ sandbox_unsupported sau policy
        with pytest.raises(DispatchError) as exc_info:
            build_hermes_cmd("deepseek-v4.1-flash", "Nội dung task")
        assert exc_info.value.reason == "sandbox_unsupported"

    def test_hermes_normalize_slug_and_reasoning(self):
        """Chuẩn hoá slug và reasoning effort thật đưa vào argv thay vì truyền raw."""
        # 1. Truyền có provider prefix -> tách slug sạch vào -m
        cmd1 = _build_hermes_argv("opencode-go/deepseek-v4.1-flash", "Prompt")
        assert cmd1[5:7] == ["-m", "deepseek-v4.1-flash"]
        assert cmd1[7:9] == ["--reasoning", "high"]

        # 2. Truyền kèm variant :low trong selector -> reasoning low
        cmd2 = _build_hermes_argv("opencode-go/deepseek-v4.1-flash:low", "Prompt")
        assert cmd2[5:7] == ["-m", "deepseek-v4.1-flash"]
        assert cmd2[7:9] == ["--reasoning", "low"]


    def test_hermes_absolute_binary(self):
        """Binary hermes phải là đường dẫn tuyệt đối qua shutil.which."""
        bin_path = get_hermes_bin()
        which_res = shutil.which("hermes")
        if which_res:
            assert bin_path == str(Path(which_res).resolve())
            assert bin_path.startswith("/")
        else:
            assert bin_path == "hermes"

    def test_hermes_default_model_and_effort(self):
        """Model auto resolve thành deepseek-v4.1-flash với reasoning high."""
        cmd = _build_hermes_argv("auto", "Prompt")
        assert cmd[0] == get_hermes_bin()
        assert cmd[1:3] == ["-z", "Prompt"]
        assert cmd[3:5] == ["--provider", "opencode-go"]
        assert cmd[5:7] == ["-m", "deepseek-v4.1-flash"]
        assert cmd[7:9] == ["--reasoning", "high"]

    def test_hermes_glm_defaults_to_effort_max(self):
        """GLM-5.3-flash mặc định nhận reasoning max theo hồ sơ duyệt."""
        cmd = _build_hermes_argv("glm-5.3-flash", "Prompt")
        assert cmd[5:7] == ["-m", "glm-5.3-flash"]
        assert cmd[7:9] == ["--reasoning", "max"]

    def test_hermes_explicit_effort_override(self):
        """Caller truyền effort tường minh phải được tôn trọng."""
        cmd = _build_hermes_argv("deepseek-v4.1-flash", "Prompt", effort="low")
        assert cmd[7:9] == ["--reasoning", "low"]

    def test_hermes_prompt_unicode_quotes_multiline_intact(self):
        """Prompt Unicode, ngoặc kép, nháy đơn, xuống dòng phải giữ nguyên sau -z."""
        complex_prompt = (
            "Dòng 1: Tiếng Việt có dấu 'nháy đơn' và \"nháy kép\"\n"
            "Dòng 2: Ký tự đặc biệt: $PATH `whoami` \\n \t /dev/null\n"
            "Dòng 3: Emoji 🚀 & Đặng Xuân Khu\n"
        )
        cmd = _build_hermes_argv("deepseek-v4.1-flash", complex_prompt)
        assert cmd[1] == "-z"
        assert cmd[2] == complex_prompt

    def test_hermes_pure_argv_helper_enforces_policy(self):
        """Helper pure argv _build_hermes_argv cũng không cho phép bypass policy."""
        with pytest.raises(DispatchContributorBlocked):
            _build_hermes_argv("opencode-go/deepseek-v4.1-flash-contributor", "Prompt")


# ===========================================================================
# 3. Policy Enforcement on All Builders (Negative & Boundary Tests)
# ===========================================================================

class TestBuilderPolicyEnforcement:
    @pytest.mark.parametrize("builder_call", [
        lambda: build_codex_cmd("gpt-6.1-sol-contributor", "read-only", None, "text"),
        lambda: build_claude_cmd("claude-opus-5.5-contributor", "prompt"),
        lambda: build_grok_cmd("grok-contributor", "read-only", None, "text", "/tmp/p"),
        lambda: build_agy_cmd("gemini-3.8-flash-contributor", "prompt"),
        lambda: build_dsh_cmd("deepseek-v4-pro-contributor", "/tmp/patch.yaml"),
        lambda: build_opencode_cmd("deepseek-v4.1-flash-contributor", "prompt"),
        lambda: build_hermes_cmd("deepseek-v4.1-flash-contributor", "prompt"),
    ])
    def test_contributor_model_blocked_on_all_builders(self, builder_call):
        """Contributor model phải bị chặn tại TẤT CẢ builders trước khi xây argv."""
        with pytest.raises(DispatchContributorBlocked) as exc_info:
            builder_call()
        assert exc_info.value.reason == "contributor_model_blocked"
        assert isinstance(exc_info.value, DispatchError)
        assert isinstance(exc_info.value, ModelPolicyViolation)
        assert isinstance(exc_info.value, ContributorModelBlocked)

    def test_write_dsh_patch_blocks_contributor_before_writing_file(self, tmp_path):
        """write_dsh_patch phải chặn model contributor TRƯỚC KHI mở file hoặc ghi đĩa."""
        patch_path = tmp_path / "patch_should_not_exist.yaml"
        with pytest.raises(DispatchContributorBlocked):
            write_dsh_patch("deepseek-v4-pro-contributor", str(patch_path))
        assert not patch_path.exists(), "File patch không được phép tạo khi model bị chặn!"

    def test_write_dsh_patch_writes_clean_patch_for_valid_model(self, tmp_path):
        """write_dsh_patch ghi patch hợp lệ cho model sạch."""
        patch_path = tmp_path / "patch_valid.yaml"
        write_dsh_patch("deepseek-v4-pro", str(patch_path))
        assert patch_path.exists()
        content = patch_path.read_text(encoding="utf-8")
        assert "deepseek-v4-pro" in content
        assert "deepseek-official" in content

    @pytest.mark.parametrize("builder_call", [
        lambda: build_codex_cmd("gpt-6.1-sol-free", "read-only", None, "text", source="auto"),
        lambda: build_claude_cmd("claude-free", "prompt", source="default"),
        lambda: build_grok_cmd("grok-free", "read-only", None, "text", "/tmp/p", source="auto"),
        lambda: build_agy_cmd("gemini-free", "prompt", source="default"),
        lambda: build_dsh_cmd("deepseek-free", "/tmp/p.yaml", source="auto"),
        lambda: build_opencode_cmd("deepseek-v4.1-flash-free", "prompt", source="auto"),
        lambda: build_hermes_cmd("deepseek-v4.1-flash-free", "prompt", source="default"),
    ])
    def test_free_model_blocked_when_selected_implicitly(self, builder_call):
        """Model free bị chặn nếu source không phải là explicit."""
        with pytest.raises(DispatchFreeBlocked) as exc_info:
            builder_call()
        assert exc_info.value.reason == "free_model_not_explicit"
        assert isinstance(exc_info.value, DispatchError)
        assert isinstance(exc_info.value, FreeModelBlocked)

    def test_free_model_allowed_when_selected_explicitly_on_go(self):
        """Model free được phép chọn TƯỜNG MINH (source=explicit) trên Go adapter (Tuan chốt 22/10)."""
        cmd_oc = _build_opencode_argv("deepseek-v4.1-flash-free", "Prompt", source="explicit")
        assert "opencode-go/deepseek-v4.1-flash-free" in cmd_oc

        cmd_he = _build_hermes_argv("glm-5.3-flash-free", "Prompt", source="explicit")
        assert "-m" in cmd_he
        idx = cmd_he.index("-m")
        assert cmd_he[idx + 1] == "glm-5.3-flash-free"

    def test_unknown_valid_model_advisory_on_codex_not_blocked(self):
        """Model unknown hợp lệ (không phải contributor hay free) không bị chặn trên codex."""
        cmd = build_codex_cmd("gpt-4", "read-only", None, "text")
        assert "-m" in cmd
        assert cmd[cmd.index("-m") + 1] == "gpt-4"

        cmd_custom = build_claude_cmd("custom-model", "test prompt")
        assert "--model" in cmd_custom
        assert cmd_custom[cmd_custom.index("--model") + 1] == "custom-model"

    def test_unapproved_go_profile_blocked(self):
        """Go adapter chỉ duyệt deepseek-v4.1-flash và glm-5.3-flash; model khác bị chặn."""
        with pytest.raises(DispatchUnapprovedProfile) as exc_info:
            build_opencode_cmd("qwen3.8-max", "prompt")
        assert exc_info.value.reason == "unapproved_go_profile"

        with pytest.raises(DispatchUnapprovedProfile) as exc_info:
            build_hermes_cmd("moonshotai-k3", "prompt")
        assert exc_info.value.reason == "unapproved_go_profile"

    def test_unapproved_go_provider_blocked(self):
        """Go builder từ chối provider khác opencode-go."""
        with pytest.raises(DispatchUnapprovedProvider) as exc_info:
            _build_opencode_argv("openrouter/deepseek-v4.1-flash", "prompt")
        assert exc_info.value.reason == "unapproved_go_provider"

    def test_claude_bounded_flags_preserved(self):
        """Tất cả cờ ToS-bounded bắt buộc của Claude phải giữ nguyên vẹn."""
        cmd = build_claude_cmd("auto", "Prompt")
        assert "--effort" in cmd and cmd[cmd.index("--effort") + 1] == "low"
        assert "--no-session-persistence" in cmd
        assert "--disable-slash-commands" in cmd
        assert "--tools" in cmd and cmd[cmd.index("--tools") + 1] == ""
        assert "--permission-mode" in cmd and cmd[cmd.index("--permission-mode") + 1] == "plan"
        assert "-p" in cmd and cmd[cmd.index("-p") + 1] == "Prompt"


# ===========================================================================
# 4. Auto Builders Shared Resolver Integration Tests
# ===========================================================================

class TestAutoBuildersResolver:
    """Kiểm tra auto builders dùng resolver chung thay cho safe_defaults hardcoded."""

    def test_auto_builders_resolve_configured_defaults(self, tmp_path):
        """Auto builders cho opencode, hermes, agy, dsh giải quyết qua resolver chung."""
        # OpenCode auto
        oc_cmd = _build_opencode_argv("auto", "Prompt")
        assert oc_cmd[3] == "opencode-go/deepseek-v4.1-flash"
        assert oc_cmd[4:6] == ["--variant", "high"]

        # Hermes auto
        he_cmd = _build_hermes_argv("auto", "Prompt")
        assert he_cmd[5:7] == ["-m", "deepseek-v4.1-flash"]
        assert he_cmd[7:9] == ["--reasoning", "high"]

        # AGY auto
        agy_cmd = build_agy_cmd("auto", "Prompt")
        idx = agy_cmd.index("--model")
        assert agy_cmd[idx + 1] == "gemini-3.8-flash-high"

        # DSH auto patch
        patch_file = tmp_path / "dsh_patch.yaml"
        write_dsh_patch("auto", str(patch_file))
        assert patch_file.exists()
        content = patch_file.read_text(encoding="utf-8")
        assert "deepseek-v4-pro" in content

