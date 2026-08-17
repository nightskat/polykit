import sys
from pathlib import Path
import pytest

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
                    "models": []
                },
                "fakevendor_with_flag": {
                    "binary": "fakebin",
                    "headless": "fakebin run '<prompt>' < /dev/null",
                    "model_flag": "--model",
                    "models": ["fake-model", "fake-4.6"]
                }
            }
        }
    
    modules_to_patch = []
    if "lib.vendor_config" in sys.modules:
        modules_to_patch.append(sys.modules["lib.vendor_config"])
    if "bin.lib.vendor_config" in sys.modules:
        modules_to_patch.append(sys.modules["bin.lib.vendor_config"])
    if "dispatch" in sys.modules:
        modules_to_patch.append(sys.modules["dispatch"])
    if "bin.dispatch" in sys.modules:
        modules_to_patch.append(sys.modules["bin.dispatch"])
        
    for mod in modules_to_patch:
        if hasattr(mod, "load_vendor_config"):
            monkeypatch.setattr(mod, "load_vendor_config", fake_load)
            
    yield
    if hasattr(vc.load_vendor_config, "cache_clear"):
        vc.load_vendor_config.cache_clear()
