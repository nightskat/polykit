from lib.states import classify, VendorState

def test_classify_not_installed(make_probe):
    probe = make_probe("codex", None, authed=True, quota_capped=False)
    assert classify(probe) == VendorState.NOT_INSTALLED

def test_classify_installed_not_authed(make_probe):
    probe = make_probe("codex", "/usr/bin/codex", authed=False, quota_capped=False)
    assert classify(probe) == VendorState.INSTALLED_NOT_AUTHED

def test_classify_quota_capped(make_probe):
    probe = make_probe("codex", "/usr/bin/codex", authed=True, quota_capped=True)
    assert classify(probe) == VendorState.QUOTA_CAPPED

def test_classify_ready(make_probe):
    probe = make_probe("codex", "/usr/bin/codex", authed=True, quota_capped=False)
    assert classify(probe) == VendorState.READY
