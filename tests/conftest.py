import os
import sys
import tempfile
from pathlib import Path
import pytest

# BUG-11 (đo 20/08/2026): mỗi lần chạy pytest bơm 8 bản ghi vào LOG THẬT
# ~/Library/Application Support/polykit/dispatch-log.jsonl — gồm cả tên vendor
# thật ("claude", reason=quota_capped). Từ khi BUG-4 cho `doctor` SUY TRẠNG THÁI
# từ chính log này, rác của test có thể làm doctor báo sai về vendor thật.
# Gốc: các test chạy bin/dispatch.py bằng subprocess, tức đi qua đúng nhánh CLI
# vẫn ghi evidence. Chặn tại nguồn: trỏ XDG_STATE_HOME vào thư mục tạm cho CẢ
# tiến trình test lẫn mọi subprocess con (chúng thừa kế os.environ).
_STATE_TMP = tempfile.mkdtemp(prefix="polykit-test-state-")
os.environ["XDG_STATE_HOME"] = _STATE_TMP

# Add bin/ to sys.path
bin_path = Path(__file__).parent.parent / "bin"
if str(bin_path) not in sys.path:
    sys.path.insert(0, str(bin_path))

from lib.states import VendorProbe

@pytest.fixture
def make_probe():
    def _make(name, path, authed=True, quota_capped=False, version="1.0", models=None):
        return VendorProbe(
            name=name,
            path=path,
            authed=authed,
            quota_capped=quota_capped,
            version=version,
            models=models or [],
            error=None
        )
    return _make

@pytest.fixture
def fake_vendors(monkeypatch):
    import sys
    # Patch all possible module paths
    import lib.vendor_config as vc
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
                    "default_model": "test-model-v1",
                    "models": ["test-model-v1"],
                },
                "fakevendor_with_flag": {
                    "binary": "fakebin",
                    "headless": "fakebin run '<prompt>' < /dev/null",
                    "model_flag": "--model",
                    "default_model": "test-model-v1",
                    "models": ["test-model-v1", "fake-model", "fake-4.6"],
                },
            },
        }
    
    modules_to_patch = []
    for mod_name in [
        "lib.vendor_config",
        "bin.lib.vendor_config",
        "lib.dispatcher",
        "bin.lib.dispatcher",
        "dispatch",
        "bin.dispatch",
    ]:
        if mod_name in sys.modules:
            modules_to_patch.append(sys.modules[mod_name])
        
    for mod in modules_to_patch:
        if hasattr(mod, "load_vendor_config"):
            monkeypatch.setattr(mod, "load_vendor_config", fake_load)
            
    yield
    if hasattr(vc.load_vendor_config, "cache_clear"):
        vc.load_vendor_config.cache_clear()
    for mod in modules_to_patch:
        if hasattr(mod, "load_vendor_config") and hasattr(mod.load_vendor_config, "cache_clear"):
            mod.load_vendor_config.cache_clear()
