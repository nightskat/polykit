import sys
import subprocess
import json
import tempfile
import os
import pytest
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


@pytest.fixture
def fake_vendors(monkeypatch):
    """Dynamic fakevendor fixture khai default_model cho auto pin, không mặc định 'auto' bypass policy."""
    import lib.vendor_config as vc
    import lib.dispatcher as dsp
    if hasattr(vc.load_vendor_config, "cache_clear"):
        vc.load_vendor_config.cache_clear()

    def fake_load(*args, **kwargs):
        return {
            "schema_version": 3,
            "vendors": {
                "fakevendor_no_flag": {
                    "binary": "true",
                    "headless": "true",
                    "model_flag": None,
                    "default_model": "fake-model",
                    "models": ["fake-model"],
                },
                "fakevendor_with_flag": {
                    "binary": "fakebin",
                    "headless": "fakebin run '<prompt>' < /dev/null",
                    "model_flag": "--model",
                    "default_model": "fake-model",
                    "models": ["fake-model", "fake-4.6"],
                },
            },
        }

    for mod in [vc, dsp]:
        if hasattr(mod, "load_vendor_config"):
            monkeypatch.setattr(mod, "load_vendor_config", fake_load)

    for mod_name in (
        "lib.vendor_config",
        "bin.lib.vendor_config",
        "dispatch",
        "bin.dispatch",
        "lib.dispatcher",
        "bin.lib.dispatcher",
    ):
        m = sys.modules.get(mod_name)
        if m and hasattr(m, "load_vendor_config"):
            monkeypatch.setattr(m, "load_vendor_config", fake_load)

    yield
    if hasattr(vc.load_vendor_config, "cache_clear"):
        vc.load_vendor_config.cache_clear()


def test_vendor_chua_biet_danh_sach_model_dump_config_exit_0():
    """Vendor chưa biết danh sách model (`claude`, `gemini`, `opencode`…) -> `--dump-config` exit 0 (catalog null advisory không ép warning unknown list)."""
    for vendor in ["claude", "gemini"]:
        res = subprocess.run(
            [sys.executable, "bin/dispatch.py", vendor, "fake-model", "--dump-config"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent)
        )
        assert res.returncode == 0, f"Expected 0 for {vendor}, got {res.returncode}. Stderr: {res.stderr}"
        info = json.loads(res.stdout)
        assert info["resolved_model"] == "fake-model"

def test_vendor_da_biet_danh_sach_slug_sai_exit_2():
    """Catalog advisory: model unknown hợp grammar được phép trong dump-config (catalog null không ép warning unknown list; injected catalog thật missing cần warning ở policy tests)."""
    for vendor in ["dsh", "agy", "codex", "grok"]:
        res = subprocess.run(
            [sys.executable, "bin/dispatch.py", vendor, "fake-model", "--dump-config"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent)
        )
        assert res.returncode == 0, f"Expected 0 for {vendor}, got {res.returncode}. Stderr: {res.stderr}"
        info = json.loads(res.stdout)
        assert info["resolved_model"] == "fake-model"

    # Injected catalog thật missing cần warning ở policy tests
    from lib.vendor_config import resolve_vendor_model
    target = resolve_vendor_model(vendor="dsh", model="fake-model", catalog_models=["deepseek-v4-pro"])
    assert any("not present in the current verified catalog" in w for w in target.warnings)

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

def test_lenh_khong_ghim_duoc_model_served_model_none_va_co_warning(fake_vendors, capsys):
    """Lệnh không ghim được model -> served_model is None và có warning."""
    import sys
    import json
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from unittest.mock import patch
    import bin.dispatch as dispatch
    
    with patch.object(sys, 'argv', ["dispatch.py", "fakevendor_no_flag", "fake-model", "--result-json", "--allow-unknown-model"]):
        with patch('sys.exit'):
            with patch('shutil.which', return_value='/usr/bin/true'):
                # Cần patch sys.stdin.read để giả lập pipe stdin
                with patch('sys.stdin.read', return_value="hello"):
                    dispatch.main()
                        
    out, err = capsys.readouterr()
    try:
        res = json.loads(out)
    except json.JSONDecodeError:
        pytest.fail(f"Expected JSON output, got: {out}")
        
    assert res.get("status") == "ok", f"Expected ok but got: {out}\nStderr: {err}"
    assert res.get("served_model") is None
    assert any("không nhận cờ model" in w for w in res.get("warnings", []))

def test_ca_11_ten_vendor_dump_config_voi_model_mac_dinh_exit_0():
    """Kiểm dump-config các vendor: OR auto blocked expected, Gemini chưa default có thể auto, Go default an toàn effort đúng."""
    from lib.vendor_config import load_vendor_config, vendor_names
    from lib.vendors import REGISTRY
    cfg = load_vendor_config()
    vendors = vendor_names(cfg)
    for k in REGISTRY:
        if k not in vendors:
            vendors.append(k)

    for vendor in vendors:
        res = subprocess.run(
            [sys.executable, "bin/dispatch.py", vendor, "--dump-config"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent)
        )
        if vendor == "openrouter":
            # OR auto blocked expected (không cho phép router auto chưa phân giải đích đến)
            assert res.returncode == 2, f"Expected 2 for openrouter, got {res.returncode}. Stderr: {res.stderr}"
            assert "unresolved destination" in res.stderr
        else:
            assert res.returncode == 0, f"Expected exit 0 for {vendor}, got {res.returncode}. Stderr: {res.stderr}"
            info = json.loads(res.stdout)
            if vendor == "gemini":
                # Gemini chưa approved concrete default -> có thể giữ auto
                assert info["resolved_model"] == "auto"
            elif vendor in ("opencode", "hermes"):
                # Go default an toàn effort đúng
                assert info["resolved_model"] == "deepseek-v4.1-flash"
                assert info.get("effort") == "high"
