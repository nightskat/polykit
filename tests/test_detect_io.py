"""Test lớp I/O detect() — inject which/runner giả, không đụng máy thật.
Bù lỗ acceptance M1b: state machine matrix test bằng probe giả, còn đây test
đúng phần detect thật (timeout, exception, auth returncode, assume_authed)."""
import subprocess
import pytest

from lib.states import classify, VendorState
from lib.vendors import detect, VendorSpec


def fake_which(path):
    """which() giả: trả path cố định hoặc None."""
    return lambda binary: path


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def spec(auth_cmd=("x", "auth"), assume=False):
    return VendorSpec(
        name="x", binary="x", auth_hint="hint",
        version_cmd=["x", "--version"], auth_check_cmd=list(auth_cmd) if auth_cmd else None,
        assume_authed=assume,
    )


def test_not_installed_when_which_none():
    p = detect(spec(), which=fake_which(None))
    assert p.path is None
    assert classify(p) is VendorState.NOT_INSTALLED


def test_ready_when_version_and_auth_ok():
    def runner(cmd, **kw):
        return FakeCompleted(returncode=0, stdout="v1.2.3")
    p = detect(spec(), which=fake_which("/bin/x"), runner=runner)
    assert p.version == "v1.2.3"
    assert p.authed is True
    assert classify(p) is VendorState.READY


def test_not_authed_when_auth_returncode_nonzero():
    def runner(cmd, **kw):
        # version ok, auth fail
        if "--version" in cmd:
            return FakeCompleted(returncode=0, stdout="v1")
        return FakeCompleted(returncode=1, stderr="not logged in")
    p = detect(spec(), which=fake_which("/bin/x"), runner=runner)
    assert p.authed is False
    assert classify(p) is VendorState.INSTALLED_NOT_AUTHED


def test_version_ignored_on_nonzero_returncode():
    """Regression Codex #2: stderr lỗi KHÔNG được dùng làm version."""
    def runner(cmd, **kw):
        return FakeCompleted(returncode=127, stdout="", stderr="command failed")
    p = detect(spec(auth_cmd=None, assume=True), which=fake_which("/bin/x"), runner=runner)
    assert p.version is None


def test_timeout_marks_error_not_authed():
    def runner(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 10)
    p = detect(spec(), which=fake_which("/bin/x"), runner=runner)
    assert p.error == "timeout"
    assert p.authed is False


def test_oserror_marks_stable_error():
    """Path chết sau which() → OSError không leak, có mã lỗi ổn định."""
    def runner(cmd, **kw):
        raise FileNotFoundError("no such file")
    p = detect(spec(), which=fake_which("/bin/x"), runner=runner)
    assert p.error.startswith("FileNotFoundError")
    assert p.authed is False


def test_assume_authed_ready_without_auth_cmd():
    """Host claude: auth_check_cmd=None + assume_authed=True → ready."""
    def runner(cmd, **kw):
        return FakeCompleted(returncode=0, stdout="v1")
    p = detect(spec(auth_cmd=None, assume=True), which=fake_which("/bin/x"), runner=runner)
    assert classify(p) is VendorState.READY


def test_no_auth_cmd_without_assume_is_not_authed():
    """Regression Codex #3: không có auth check + không assume → KHÔNG mark ready."""
    def runner(cmd, **kw):
        return FakeCompleted(returncode=0, stdout="v1")
    p = detect(spec(auth_cmd=None, assume=False), which=fake_which("/bin/x"), runner=runner)
    assert classify(p) is VendorState.INSTALLED_NOT_AUTHED


def test_run_doctor_with_injected_probes_no_worker(tmp_path, monkeypatch):
    """run_doctor không detect thật khi truyền probes; không spawn worker Claude."""
    import doctor as doctor_mod
    from lib.states import VendorProbe
    calls = []
    monkeypatch.setattr(doctor_mod, "write_state", lambda s, path=None: calls.append(s) or path)
    probes = [VendorProbe(name="claude", path="/bin/claude", authed=True, quota_capped=False)]
    state = doctor_mod.run_doctor(probes=probes, now="2026-07-13T00:00:00Z")
    assert state["schema_version"] == 1
    assert state["vendors"]["claude"]["state"] == "ready"
    assert len(calls) == 1  # write_state gọi đúng 1 lần, không detect_all
