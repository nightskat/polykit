"""Lô 11 — cổng data_class=code-nopii cho lane Go unsandboxed (opencode/hermes).

Bất biến được kiểm ở đây:
- Không có cờ data_class chính xác 'code-nopii' ⇒ vẫn sandbox_unsupported.
- Bất kỳ attachment / synthetic_vision / allow_sensitive_vision /
  sensitive_confirmation ⇒ blocked, kể cả khi KHÔNG có file.
- pg-redact check prompt: pass ⇒ chạy; PII / exit khác 0 / timeout / lỗi ⇒
  blocked TRƯỚC detector/probe/vendor spawn; không lộ prompt/checker output.
- Temp file nằm trong TMPDIR và bị xoá sau khi kiểm.
- GO_SANDBOX_CONFINED không phải bypass; không có bool/value-object nào thay cờ.
- Result JSON đường opt-in: unsandboxed=true, data_class=code-nopii, kể cả
  khi lỗi/timeout sau cổng; served_model không đoán.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from lib.dispatch_core import (
    DispatchError,
    DispatchResult,
    GO_SANDBOX_CONFINED,
    build_hermes_cmd,
    build_opencode_cmd,
)
from lib.dispatcher import _run_vendor, run_vendor
from lib.go_data_gate import (
    DATA_CLASS_CODE_NOPII,
    GoDataGateBlocked,
    evaluate_go_data_gate,
)
from lib.states import VendorProbe

REPO_ROOT = Path(__file__).resolve().parents[1]
GO_VENDORS = ("opencode", "hermes")


# ---------------------------------------------------------------------------
# Spy / stub
# ---------------------------------------------------------------------------

class SpyDetector:
    def __init__(self, ready=True):
        self.called = False
        self.ready = ready

    def __call__(self, spec):
        self.called = True
        return VendorProbe(
            name=getattr(spec, "name", "x"),
            path="/bin/x",
            authed=self.ready,
            quota_capped=False,
        )


class SpyRunner:
    def __init__(self, stdout="ok", exc=None):
        self.called = False
        self.calls = []
        self.stdout = stdout
        self.exc = exc

    def __call__(self, cmd, **kwargs):
        self.called = True
        self.calls.append((cmd, kwargs))
        if self.exc is not None:
            raise self.exc
        return subprocess.CompletedProcess(cmd, 0, stdout=self.stdout, stderr="")


class SpyChecker:
    """Thay pg-redact: ghi lại argv, trả returncode/exception tuỳ kịch bản."""

    def __init__(self, returncode=0, exc=None, stdout="", seen_paths=None):
        self.returncode = returncode
        self.exc = exc
        self.stdout = stdout
        self.called = 0
        self.paths = seen_paths if seen_paths is not None else []

    def __call__(self, cmd, **kwargs):
        self.called += 1
        self.paths.append(cmd[-1])
        if self.exc is not None:
            raise self.exc
        return subprocess.CompletedProcess(cmd, self.returncode, stdout=self.stdout, stderr="")


@pytest.fixture
def checker_pass(monkeypatch):
    import lib.go_data_gate as gate_mod

    spy = SpyChecker(returncode=0)
    monkeypatch.setattr(gate_mod, "_which", lambda name: "/usr/bin/pg-redact")
    monkeypatch.setattr(gate_mod, "_checker_runner", spy)
    return spy


@pytest.fixture
def checker_missing(monkeypatch):
    import lib.go_data_gate as gate_mod

    monkeypatch.setattr(gate_mod, "_which", lambda name: None)


# ---------------------------------------------------------------------------
# 1. Cổng thuần (gate unit)
# ---------------------------------------------------------------------------

def test_gate_missing_or_wrong_data_class_blocks():
    for bad in (None, "", "pii", "code_nopii", " code-nopii", "CODE-NOPII"):
        with pytest.raises(GoDataGateBlocked) as exc:
            evaluate_go_data_gate(data_class=bad, prompt="print(1)", vendor="opencode")
        assert exc.value.reason == "sandbox_unsupported"
        assert "code-nopii" in str(exc.value)


def test_gate_attachment_blocked_even_with_optin(checker_missing):
    with pytest.raises(GoDataGateBlocked) as exc:
        evaluate_go_data_gate(
            data_class=DATA_CLASS_CODE_NOPII,
            prompt="code",
            attachments=["/tmp/anh.png"],
            vendor="opencode",
        )
    assert exc.value.reason == "vision_blocked"


def test_gate_vision_flags_block_without_any_file(checker_missing):
    cases = [
        {"synthetic_vision": True},
        {"allow_sensitive_vision": True},
        {"sensitive_confirmation": object()},
    ]
    for kw in cases:
        with pytest.raises(GoDataGateBlocked) as exc:
            evaluate_go_data_gate(
                data_class=DATA_CLASS_CODE_NOPII, prompt="code", vendor="hermes", **kw
            )
        assert exc.value.reason == "vision_blocked", kw


def test_gate_checker_pass_writes_tmpdir_and_deletes_temp(monkeypatch):
    import lib.go_data_gate as gate_mod

    spy = SpyChecker(returncode=0)
    monkeypatch.setattr(gate_mod, "_which", lambda name: "/usr/bin/pg-redact")
    monkeypatch.setattr(gate_mod, "_checker_runner", spy)

    warnings = evaluate_go_data_gate(
        data_class=DATA_CLASS_CODE_NOPII, prompt="def f(): return 1", vendor="opencode"
    )
    assert warnings == []
    assert spy.called == 1
    path = Path(spy.paths[0])
    assert path.parent == Path(tempfile.gettempdir())
    assert not path.exists(), "temp prompt phải bị xoá sau khi check"


def test_gate_checker_pii_blocks_without_leaking_prompt_or_output(monkeypatch):
    import lib.go_data_gate as gate_mod

    prompt = "khach Nguyen Van A CCCD 012345678901"
    spy = SpyChecker(returncode=1, stdout="PHÁT HIỆN PII: KH? Nguyen *** A 0123******01")
    monkeypatch.setattr(gate_mod, "_which", lambda name: "/usr/bin/pg-redact")
    monkeypatch.setattr(gate_mod, "_checker_runner", spy)

    with pytest.raises(GoDataGateBlocked) as exc:
        evaluate_go_data_gate(
            data_class=DATA_CLASS_CODE_NOPII, prompt=prompt, vendor="opencode"
        )
    assert exc.value.reason == "pii_detected"
    msg = str(exc.value)
    assert prompt not in msg
    assert "012345678901" not in msg
    assert "Nguyen *** A" not in msg
    assert not Path(spy.paths[0]).exists()


def test_gate_checker_timeout_blocks(monkeypatch):
    import lib.go_data_gate as gate_mod

    spy = SpyChecker(exc=subprocess.TimeoutExpired(cmd="pg-redact", timeout=20))
    monkeypatch.setattr(gate_mod, "_which", lambda name: "/usr/bin/pg-redact")
    monkeypatch.setattr(gate_mod, "_checker_runner", spy)

    with pytest.raises(GoDataGateBlocked) as exc:
        evaluate_go_data_gate(
            data_class=DATA_CLASS_CODE_NOPII, prompt="code", vendor="hermes"
        )
    assert exc.value.reason == "pii_checker_failed"
    assert not Path(spy.paths[0]).exists()


def test_gate_checker_error_blocks(monkeypatch):
    import lib.go_data_gate as gate_mod

    spy = SpyChecker(exc=OSError("boom"))
    monkeypatch.setattr(gate_mod, "_which", lambda name: "/usr/bin/pg-redact")
    monkeypatch.setattr(gate_mod, "_checker_runner", spy)

    with pytest.raises(GoDataGateBlocked) as exc:
        evaluate_go_data_gate(
            data_class=DATA_CLASS_CODE_NOPII, prompt="code", vendor="opencode"
        )
    assert exc.value.reason == "pii_checker_failed"


def test_gate_missing_checker_warns_but_allows_text(checker_missing):
    warnings = evaluate_go_data_gate(
        data_class=DATA_CLASS_CODE_NOPII, prompt="code", vendor="opencode"
    )
    joined = "\n".join(warnings)
    assert "pg-redact" in joined
    assert DATA_CLASS_CODE_NOPII in joined
    # Vẫn cấm attachment dù checker vắng mặt.
    with pytest.raises(GoDataGateBlocked) as exc:
        evaluate_go_data_gate(
            data_class=DATA_CLASS_CODE_NOPII,
            prompt="code",
            attachments=["/tmp/a.png"],
            vendor="opencode",
        )
    assert exc.value.reason == "vision_blocked"


# ---------------------------------------------------------------------------
# 2. Builders (lib) — mỗi vendor × có/không opt-in
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("builder,kwargs", [
    (build_opencode_cmd, {"attachments": None}),
    (build_hermes_cmd, {}),
])
def test_builder_without_optin_blocked(builder, kwargs):
    with pytest.raises(DispatchError) as exc:
        builder("deepseek-v4.1-flash", "print(1)", **kwargs)
    assert exc.value.reason == "sandbox_unsupported"
    assert "Plan mục 83" in str(exc.value)


@pytest.mark.parametrize("builder", [build_opencode_cmd, build_hermes_cmd])
def test_builder_optin_builds_argv(builder, checker_pass):
    cmd = builder("deepseek-v4.1-flash", "print(1)",
                  data_class=DATA_CLASS_CODE_NOPII)
    assert isinstance(cmd, list) and cmd
    assert "print(1)" in cmd
    assert checker_pass.called == 1


@pytest.mark.parametrize("builder", [build_opencode_cmd, build_hermes_cmd])
def test_builder_pii_blocked_before_argv(builder, monkeypatch):
    import lib.go_data_gate as gate_mod

    spy = SpyChecker(returncode=1)
    monkeypatch.setattr(gate_mod, "_which", lambda name: "/usr/bin/pg-redact")
    monkeypatch.setattr(gate_mod, "_checker_runner", spy)
    with pytest.raises(DispatchError) as exc:
        builder("deepseek-v4.1-flash", "CCCD 012345678901",
                data_class=DATA_CLASS_CODE_NOPII)
    assert exc.value.reason == "pii_detected"


def test_opencode_builder_attachment_blocked(checker_pass):
    with pytest.raises(DispatchError) as exc:
        build_opencode_cmd("deepseek-v4.1-flash", "print(1)",
                           attachments=["/tmp/a.png"],
                           data_class=DATA_CLASS_CODE_NOPII)
    assert exc.value.reason == "vision_blocked"
    assert checker_pass.called == 0, "chặn attachment trước cả checker"


def test_confinement_constant_is_not_bypass(monkeypatch):
    """Lật GO_SANDBOX_CONFINED=True KHÔNG mở lane; cờ bool giả cũng không."""
    import lib.dispatch_core as dc

    monkeypatch.setattr(dc, "GO_SANDBOX_CONFINED", True)
    assert GO_SANDBOX_CONFINED is False, "production default phải là False"
    with pytest.raises(DispatchError) as exc:
        build_opencode_cmd("deepseek-v4.1-flash", "print(1)")
    assert exc.value.reason == "sandbox_unsupported"

    import inspect

    for fn in (build_opencode_cmd, build_hermes_cmd):
        params = inspect.signature(fn).parameters
        for banned in ("evidence_sandbox", "sandbox_verified", "allow_unsandboxed",
                       "bypass", "skip_gate"):
            assert banned not in params, (fn.__name__, banned)


# ---------------------------------------------------------------------------
# 3. Entrypoint thư viện run_vendor — mỗi vendor × có/không opt-in
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("vendor", GO_VENDORS)
def test_run_vendor_without_optin_blocked_before_detector(vendor, checker_pass):
    det, run = SpyDetector(), SpyRunner()
    res = run_vendor(vendor=vendor, prompt="print(1)", model="auto",
                     runner=run, detector=det)
    assert res.status == "blocked"
    assert res.reason == "sandbox_unsupported"
    assert res.unsandboxed is False and res.data_class is None
    assert det.called is False and run.called is False
    assert checker_pass.called == 0, "chưa opt-in thì chưa được chạy checker"


@pytest.mark.parametrize("vendor", GO_VENDORS)
def test_run_vendor_optin_runs_with_result_json_fields(vendor, checker_pass):
    det, run = SpyDetector(), SpyRunner(stdout="done")
    res = run_vendor(vendor=vendor, prompt="print(1)", model="auto",
                     runner=run, detector=det,
                     data_class=DATA_CLASS_CODE_NOPII)
    assert res.status == "ok", res.warnings
    assert det.called and run.called
    assert res.unsandboxed is True
    assert res.data_class == DATA_CLASS_CODE_NOPII
    assert res.served_model is None  # không đoán model đã phục vụ
    payload = res.to_dict()
    assert payload["unsandboxed"] is True
    assert payload["data_class"] == DATA_CLASS_CODE_NOPII
    # argv là list, stdin DEVNULL
    cmd, kwargs = run.calls[0]
    assert isinstance(cmd, list)
    assert kwargs["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize("vendor", GO_VENDORS)
def test_run_vendor_optin_pii_blocked_before_detector(vendor, monkeypatch):
    import lib.go_data_gate as gate_mod

    monkeypatch.setattr(gate_mod, "_which", lambda name: "/usr/bin/pg-redact")
    monkeypatch.setattr(gate_mod, "_checker_runner", SpyChecker(returncode=1))
    det, run = SpyDetector(), SpyRunner()
    res = run_vendor(vendor=vendor, prompt="CCCD 012345678901", model="auto",
                     runner=run, detector=det,
                     data_class=DATA_CLASS_CODE_NOPII)
    assert res.status == "blocked" and res.reason == "pii_detected"
    assert res.unsandboxed is False
    assert res.data_class == DATA_CLASS_CODE_NOPII
    assert det.called is False and run.called is False
    assert "012345678901" not in json.dumps(res.to_dict())


@pytest.mark.parametrize("vendor", GO_VENDORS)
def test_run_vendor_optin_attachment_blocked_before_detector(vendor, checker_pass):
    det, run = SpyDetector(), SpyRunner()
    res = run_vendor(vendor=vendor, prompt="print(1)", model="auto",
                     runner=run, detector=det,
                     attachments=["/tmp/anh.png"],
                     synthetic_vision=True,
                     data_class=DATA_CLASS_CODE_NOPII)
    assert res.status == "blocked" and res.reason == "vision_blocked"
    assert det.called is False and run.called is False
    assert checker_pass.called == 0


@pytest.mark.parametrize("vendor", GO_VENDORS)
def test_run_vendor_optin_sensitive_flag_without_file_blocked(vendor, checker_pass):
    det, run = SpyDetector(), SpyRunner()
    res = run_vendor(vendor=vendor, prompt="print(1)", model="auto",
                     runner=run, detector=det,
                     allow_sensitive_vision=True,
                     data_class=DATA_CLASS_CODE_NOPII)
    assert res.status == "blocked" and res.reason == "vision_blocked"
    assert det.called is False and run.called is False


@pytest.mark.parametrize("vendor", GO_VENDORS)
def test_run_vendor_optin_checker_timeout_blocks_before_detector(vendor, monkeypatch):
    import lib.go_data_gate as gate_mod

    monkeypatch.setattr(gate_mod, "_which", lambda name: "/usr/bin/pg-redact")
    monkeypatch.setattr(
        gate_mod, "_checker_runner",
        SpyChecker(exc=subprocess.TimeoutExpired(cmd="pg-redact", timeout=20)),
    )
    det, run = SpyDetector(), SpyRunner()
    res = run_vendor(vendor=vendor, prompt="print(1)", model="auto",
                     runner=run, detector=det,
                     data_class=DATA_CLASS_CODE_NOPII)
    assert res.status == "blocked" and res.reason == "pii_checker_failed"
    assert det.called is False and run.called is False


@pytest.mark.parametrize("vendor", GO_VENDORS)
def test_run_vendor_optin_error_after_gate_keeps_json_fields(vendor, checker_pass):
    det = SpyDetector()
    run = SpyRunner(exc=RuntimeError("vendor boom"))
    res = run_vendor(vendor=vendor, prompt="print(1)", model="auto",
                     runner=run, detector=det,
                     data_class=DATA_CLASS_CODE_NOPII)
    assert res.status == "error"
    assert res.unsandboxed is True
    assert res.data_class == DATA_CLASS_CODE_NOPII


@pytest.mark.parametrize("vendor", GO_VENDORS)
def test_run_vendor_optin_timeout_after_gate_keeps_json_fields(vendor, checker_pass):
    det = SpyDetector()
    run = SpyRunner(exc=subprocess.TimeoutExpired(cmd="x", timeout=1))
    res = run_vendor(vendor=vendor, prompt="print(1)", model="auto",
                     runner=run, detector=det, timeout=5,
                     data_class=DATA_CLASS_CODE_NOPII)
    assert res.status == "timeout"
    assert res.unsandboxed is True
    assert res.data_class == DATA_CLASS_CODE_NOPII


def test_run_vendor_non_go_vendor_ignores_data_class(checker_pass):
    """Cổng Go không đụng vendor khác (codex vẫn chạy bình thường)."""
    det, run = SpyDetector(), SpyRunner(stdout="done")
    res = run_vendor(vendor="codex", prompt="print(1)", model="auto",
                     runner=run, detector=det,
                     data_class=DATA_CLASS_CODE_NOPII)
    assert res.status == "ok"
    assert res.unsandboxed is False
    assert res.data_class is None
    assert checker_pass.called == 0


# ---------------------------------------------------------------------------
# 4. CLI (bin/dispatch.py) — không opt-in / cờ sai / attachment
# ---------------------------------------------------------------------------

def _cli(*argv, prompt="print(1)"):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "bin" / "dispatch.py"), *argv,
         "--prompt", prompt, "--result-json"],
        capture_output=True, text=True, timeout=120,
    )


@pytest.mark.parametrize("vendor", GO_VENDORS)
def test_cli_no_optin_blocked_json(vendor):
    proc = _cli(vendor, "auto")
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["status"] == "blocked"
    assert data["reason"] == "sandbox_unsupported"
    assert data["unsandboxed"] is False
    assert data["data_class"] is None


@pytest.mark.parametrize("vendor", GO_VENDORS)
def test_cli_wrong_data_class_blocked_json(vendor):
    proc = _cli(vendor, "auto", "--data-class", "pii")
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["status"] == "blocked"
    assert data["reason"] == "sandbox_unsupported"
    assert data["data_class"] == "pii"


@pytest.mark.skipif(
    __import__("shutil").which("pg-redact") is None,
    reason="pg-redact không có trên máy — nhánh checker thật không chạy được",
)
def test_cli_optin_real_checker_blocks_pii_before_spawn():
    proc = _cli("opencode", "auto", "--data-class", "code-nopii",
                prompt="Nguyen Van A CCCD 012345678901")
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["status"] == "blocked"
    assert data["reason"] == "pii_detected"
    assert data["unsandboxed"] is False
    assert data["data_class"] == DATA_CLASS_CODE_NOPII
    assert "012345678901" not in proc.stdout
    assert "012345678901" not in proc.stderr


@pytest.mark.parametrize("vendor", GO_VENDORS)
def test_cli_optin_attachment_blocked(vendor, checker_pass):
    proc = _cli(vendor, "auto", "--data-class", "code-nopii",
                "--synthetic-vision", "-f", "/tmp/khong_ton_tai.png")
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["status"] == "blocked"
    assert data["reason"] == "vision_blocked"
    assert data["unsandboxed"] is False
    assert checker_pass.called == 0, "chặn attachment trước checker/detector/spawn"
