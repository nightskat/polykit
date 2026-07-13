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
