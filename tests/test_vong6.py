import sys
import json
import subprocess
import pytest
import os

@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_bin = bin_dir / "claude"
    
    fake_bin.write_text("""#!/bin/bash
if [ -n "$FAKE_OC_FAIL" ]; then
    echo "boom: fake fail" >&2
    exit 1
fi
if [ -n "$FAKE_OC_QUOTA" ]; then
    echo "insufficient credit" >&2
    exit 146
fi
echo "fake ok output"
exit 0
""")
    fake_bin.chmod(0o755)
    
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    return fake_bin

def run_cli(args, env=None):
    py = sys.executable
    cmd = [py, "bin/dispatch.py"] + args
    e = os.environ.copy()
    if env:
        e.update(env)
    res = subprocess.run(cmd, capture_output=True, text=True, input="hi", env=e)
    return res

def test_vong6_error_branch(fake_claude):
    res = run_cli(["claude", "--no-traps", "--result-json", "--allow-unknown-model"], env={"FAKE_OC_FAIL": "1"})
    data = json.loads(res.stdout)
    assert data["status"] == "error"
    assert data["served_model"] == "claude-opus-5", f"Expected claude-opus-5, got {data['served_model']}"
    assert not any("không nhận cờ model" in w for w in data["warnings"])
    assert "không nhận cờ model" not in res.stderr

def test_vong6_quota_branch(fake_claude):
    res = run_cli(["claude", "--no-traps", "--result-json", "--allow-unknown-model"], env={"FAKE_OC_QUOTA": "1"})
    data = json.loads(res.stdout)
    assert data["status"] == "skipped"
    assert data["reason"] == "quota_capped"
    assert data["served_model"] == "claude-opus-5", f"Expected claude-opus-5, got {data['served_model']}"
    assert not any("không nhận cờ model" in w for w in data["warnings"])
    assert "không nhận cờ model" not in res.stderr

def test_vong6_ok_branch(fake_claude):
    res = run_cli(["claude", "--no-traps", "--result-json", "--allow-unknown-model"])
    data = json.loads(res.stdout)
    assert data["status"] == "ok"
    assert data["served_model"] == "claude-opus-5", f"Expected claude-opus-5, got {data['served_model']}"
    assert not any("không nhận cờ model" in w for w in data["warnings"])
    assert "không nhận cờ model" not in res.stderr

def test_vong7_text_duplicate_warning(fake_claude):
    res = run_cli(["claude", "--no-traps", "--allow-unknown-model"], env={"FAKE_OC_FAIL": "1"})
    assert res.returncode == 1
    # Warning should appear exactly once in stderr
    count = res.stderr.count("không nhận cờ model")
    assert count == 0, f"Expected exactly 0 warning, got {count}. stderr:\\n{res.stderr}"

def test_vong6_not_installed_branch(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    res = run_cli(["claude", "--no-traps", "--result-json", "--allow-unknown-model"])
    data = json.loads(res.stdout)
    assert data["status"] == "skipped"
    assert data["reason"] == "not_installed"
    assert data["served_model"] == "claude-opus-5", f"Expected claude-opus-5, got {data['served_model']}"
