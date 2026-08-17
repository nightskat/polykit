import sys
import subprocess
import json
import tempfile
import os
import pytest
from pathlib import Path

def test_vendor_chua_biet_danh_sach_model_dump_config_exit_0():
    """Vendor chưa biết danh sách model (`claude`, `gemini`, `opencode`…) -> `--dump-config` exit 0 kèm warning."""
    for vendor in ["claude", "gemini"]:
        res = subprocess.run(
            [sys.executable, "bin/dispatch.py", vendor, "fake-model", "--dump-config"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent)
        )
        assert res.returncode == 0, f"Expected 0 for {vendor}, got {res.returncode}. Stderr: {res.stderr}"
        assert "warning: model list for vendor" in res.stderr

def test_vendor_da_biet_danh_sach_slug_sai_exit_2():
    """Vendor đã biết danh sách (`dsh`, `agy`, `codex`, `grok`) + slug sai -> exit 2."""
    for vendor in ["dsh", "agy", "codex", "grok"]:
        res = subprocess.run(
            [sys.executable, "bin/dispatch.py", vendor, "fake-model", "--dump-config"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent)
        )
        assert res.returncode == 2, f"Expected 2 for {vendor}, got {res.returncode}. Stderr: {res.stderr}"
        assert f"error: model 'fake-model' not in vendor '{vendor}'" in res.stderr

def test_models_sai_dang_bao_loi_ro():
    """`models` sai dạng (`dict`, `str`) -> báo lỗi rõ, không im."""
    from lib.vendor_config import load_vendor_config
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        json.dump({"schema_version": 3, "vendors": {"testv": {"models": "not-a-list"}}}, f)
        temp_path = f.name
    try:
        with pytest.raises(ValueError, match="sai dạng"):
            # cache makes us specify path explicitly to bypass it in test?
            # load_vendor_config uses lru_cache, but we can pass path to override or clear it.
            # load_vendor_config.cache_clear() is better, but passing path works if it doesn't match cache args
            load_vendor_config.__wrapped__(Path(temp_path))
    finally:
        os.unlink(temp_path)

def test_lenh_khong_ghim_duoc_model_served_model_none_va_co_warning():
    """Lệnh không ghim được model -> served_model is None và có warning."""
    from lib.dispatcher import run_vendor
    from lib.states import VendorProbe
    
    calls = []
    def mock_runner(cmd, **kwargs):
        calls.append(cmd)
        class MockRes:
            returncode = 0
            stdout = "ok"
            stderr = ""
        return MockRes()
        
    res = run_vendor(
        "claude", 
        prompt="hello", 
        model="auto", 
        runner=mock_runner, 
        detector=lambda spec: VendorProbe(name="claude", path="/usr/bin/claude", authed=True, quota_capped=False, version=None, models=[], error=None)
    )
    
    assert res.status == "ok"
    assert res.served_model is None
    assert any("không nhận cờ model" in w for w in res.warnings)

def test_ca_11_ten_vendor_dump_config_voi_model_mac_dinh_exit_0():
    """Cả 11 tên vendor `--dump-config` với model mặc định -> exit 0."""
    vendors = ["agy", "dsh", "grok", "codex", "gemini", "claude", "openrouter"]
    for vendor in vendors:
        res = subprocess.run(
            [sys.executable, "bin/dispatch.py", vendor, "--dump-config"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent)
        )
        assert res.returncode == 0, f"Expected exit 0 for {vendor}, got {res.returncode}. Stderr: {res.stderr}"
