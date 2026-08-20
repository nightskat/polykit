from pathlib import Path
from lib.dispatch_core import build_codex_cmd, build_grok_cmd, gemini_agy_tier

def test_build_codex_cmd():
    # Model auto, read-only sandbox, no workdir, text format
    cmd1 = build_codex_cmd(model="auto", sandbox="read-only", workdir=None, fmt="text")
    # Bench 20/08: PolyKit ghim effort `low` (codex mặc định `medium` = ô tệ nhất).
    assert cmd1 == ["codex", "exec", "-c", "model_reasoning_effort=low",
                    "-s", "read-only", "--skip-git-repo-check"]

    # Model specific, workspace-write, workdir present, json format
    cmd2 = build_codex_cmd(model="gpt-4", sandbox="workspace-write", workdir="/my/project", fmt="json")
    assert cmd2 == ["codex", "exec", "-m", "gpt-4", "-c", "model_reasoning_effort=low",
                    "-s", "workspace-write", "--json", "-C", "/my/project", "--skip-git-repo-check"]

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
    # 3.6 Flash (newest) — bare effort suffixes + auto default
    assert gemini_agy_tier("gemini-3.6-flash-high") == "high"
    assert gemini_agy_tier("gemini-3.6-flash-low") == "low"
    assert gemini_agy_tier("gemini-3.6-flash-medium") == "med"
    assert gemini_agy_tier("auto") == "med"
    # 3.5 Flash — quota-friendly, routed to f35 tiers
    assert gemini_agy_tier("gemini-3.5-flash-high") == "f35-high"
    assert gemini_agy_tier("gemini-3.5-flash-low") == "f35-low"
    assert gemini_agy_tier("gemini-3.5-flash") == "f35"


# ── effort codex: bench 20/08 ───────────────────────────────────────────────

def test_codex_ghim_effort_low_va_chan_muc_la():
    """codex KHÔNG có cờ --effort; chỉnh qua -c model_reasoning_effort=<mức>.
    Mặc định của codex là `medium` — bench 20/08 cho thấy đó là ô tệ nhất
    (515 reasoning tok → 2/5 lỗi, so với low 366 → 3/5)."""
    import pytest
    from lib.dispatch_core import build_codex_cmd, DispatchError

    cmd = build_codex_cmd("auto", "read-only", None, "text")
    i = cmd.index("-c")
    assert cmd[i + 1] == "model_reasoning_effort=low"

    cmd = build_codex_cmd("auto", "read-only", None, "text", effort="high")
    assert "model_reasoning_effort=high" in cmd

    with pytest.raises(DispatchError):
        build_codex_cmd("auto", "read-only", None, "text", effort="sieu-cao")


def test_minimal_van_hop_le_nhung_da_ghi_trap():
    """`minimal` là giá trị codex chấp nhận nên builder không chặn — nhưng bench
    đo được nó trả RỖNG (0 token, 0 kết quả). Cảnh báo nằm ở vendors.json."""
    import json as _j
    from pathlib import Path as _P
    from lib.dispatch_core import build_codex_cmd
    assert "model_reasoning_effort=minimal" in build_codex_cmd(
        "auto", "read-only", None, "text", effort="minimal")
    cfg = _j.loads((_P(__file__).resolve().parents[1] / "config" / "vendors.json").read_text())
    assert "RỖNG" in cfg["vendors"]["codex"]["effort_flag_note"]
