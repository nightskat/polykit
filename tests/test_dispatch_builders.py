from pathlib import Path
from lib.dispatch_core import build_codex_cmd, build_grok_cmd, gemini_agy_tier

def test_build_codex_cmd():
    # Model auto, read-only sandbox, no workdir, text format
    cmd1 = build_codex_cmd(model="auto", sandbox="read-only", workdir=None, fmt="text")
    assert cmd1 == ["codex", "exec", "-s", "read-only", "--skip-git-repo-check"]

    # Model specific, workspace-write, workdir present, json format
    cmd2 = build_codex_cmd(model="gpt-4", sandbox="workspace-write", workdir="/my/project", fmt="json")
    assert cmd2 == ["codex", "exec", "-m", "gpt-4", "-s", "workspace-write", "--json", "-C", "/my/project"]

def test_build_grok_cmd():
    grok_bin = str(Path.home() / ".grok/bin/grok")
    
    # Read-only sandbox
    cmd_ro = build_grok_cmd(model="auto", sandbox="read-only", workdir=None, fmt="text", prompt_file="/tmp/prompt")
    assert cmd_ro == [
        grok_bin, "--prompt-file", "/tmp/prompt",
        "--tools", "read_file,grep,list_dir", "--always-approve"
    ]

    # Workspace-write sandbox, specific model, workdir, json format
    cmd_ww = build_grok_cmd(model="grok-2", sandbox="workspace-write", workdir="/my/project", fmt="json", prompt_file="/tmp/prompt")
    assert cmd_ww == [
        grok_bin, "--prompt-file", "/tmp/prompt",
        "-m", "grok-2", "--output-format", "json", "--cwd", "/my/project",
        "--disallowed-tools", "run_terminal_cmd,web_search,web_fetch,task,Agent",
        "--permission-mode", "acceptEdits"
    ]

def test_gemini_agy_tier():
    assert gemini_agy_tier("gemini-3.1-pro-high") == "pro-high"
    assert gemini_agy_tier("gemini-3.1-pro-low") == "pro-low"
    assert gemini_agy_tier("gemini-3.1-pro") == "pro-low"
    assert gemini_agy_tier("gemini-3.5-flash-high") == "high"
    assert gemini_agy_tier("gemini-3.5-flash-low") == "low"
    assert gemini_agy_tier("gemini-2.5-flash") == "med"
    assert gemini_agy_tier("auto") == "med"
