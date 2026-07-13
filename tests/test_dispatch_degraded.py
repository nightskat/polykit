import pytest
from lib.dispatcher import run_vendor
from lib.states import VendorProbe
from lib.vendors import VendorSpec

def test_codex_degraded_not_installed():
    called = False
    def mock_runner(cmd, **kwargs):
        nonlocal called
        called = True
        return None
        
    def mock_detector(spec: VendorSpec) -> VendorProbe:
        return VendorProbe(
            name=spec.name,
            path=None,  # triggers NOT_INSTALLED
            authed=False,
            quota_capped=False
        )

    result = run_vendor(
        vendor="codex",
        prompt="hello",
        runner=mock_runner,
        detector=mock_detector
    )
    
    assert result.status == "skipped"
    assert result.reason == "not_installed"
    assert "skipped: not_installed" in result.summary
    assert not called

def test_codex_degraded_not_authed():
    called = False
    def mock_runner(cmd, **kwargs):
        nonlocal called
        called = True
        return None
        
    def mock_detector(spec: VendorSpec) -> VendorProbe:
        return VendorProbe(
            name=spec.name,
            path="/usr/local/bin/codex",
            authed=False,  # triggers INSTALLED_NOT_AUTHED
            quota_capped=False
        )

    result = run_vendor(
        vendor="codex",
        prompt="hello",
        runner=mock_runner,
        detector=mock_detector
    )
    
    assert result.status == "skipped"
    assert result.reason == "installed_not_authed"
    assert "skipped: installed_not_authed" in result.summary
    assert not called

def test_codex_degraded_quota_capped():
    called = False
    def mock_runner(cmd, **kwargs):
        nonlocal called
        called = True
        return None
        
    def mock_detector(spec: VendorSpec) -> VendorProbe:
        return VendorProbe(
            name=spec.name,
            path="/usr/local/bin/codex",
            authed=True,
            quota_capped=True  # triggers QUOTA_CAPPED
        )

    result = run_vendor(
        vendor="codex",
        prompt="hello",
        runner=mock_runner,
        detector=mock_detector
    )
    
    assert result.status == "skipped"
    assert result.reason == "quota_capped"
    assert "skipped: quota_capped" in result.summary
    assert not called
