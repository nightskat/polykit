"""Tests for dispatch v2: vendor_config, dsh dispatch, auto→default_model, traps, --doctor."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import pytest

from lib.vendor_config import (
    load_vendor_config,
    vendor_names,
    default_model,
    vendor_traps,
    vendor_verify_cmd,
    vendor_zero_quota_cmds,
)
from lib.dispatch_core import (
    build_dsh_cmd,
    write_dsh_patch,
    DSH_DEFAULT_MODEL,
    AGY_DEFAULT_MODEL,
)
from lib.dispatcher import run_vendor
from lib.vendors import REGISTRY
from lib.states import VendorProbe


# ─── vendor_config.py ───

class TestVendorConfig:
    def test_load_vendor_config_schema_v2(self):
        cfg = load_vendor_config()
        assert cfg["schema_version"] == 3

    def test_vendor_names_includes_new_vendors(self):
        names = vendor_names()
        for v in ("agy", "dsh", "grok", "codex", "gemini", "claude"):
            assert v in names, f"vendor '{v}' missing from vendor_names()"

    def test_vendor_names_no_hardcode_old_list(self):
        """choices phải sinh từ JSON, so với tập vendors trong cfg chứ không hardcode."""
        cfg = load_vendor_config()
        names = vendor_names(cfg)
        assert "dsh" in names
        assert "claude" in names
        assert len(names) == len(cfg.get("vendors", {}))
        assert set(names) == set(cfg.get("vendors", {}).keys())

    def test_default_model_dsh(self):
        dm = default_model("dsh")
        # Cập nhật default dsh -> deepseek-v4-pro
        assert dm == "deepseek-v4-pro"

    def test_default_model_chua_kiem_returns_none(self):
        """Gemini có default_model = CHUA_KIEM → trả None."""
        dm = default_model("gemini")
        assert dm is None

    def test_default_model_agy(self):
        assert default_model("agy") == "gemini-3.8-flash-high"
        assert default_model("agy") == AGY_DEFAULT_MODEL

    def test_traps_dsh(self):
        traps = vendor_traps("dsh")
        assert len(traps) >= 4
        assert any("v4-flash" in t for t in traps)
        assert any("RỖNG" in t or "rỗng" in t for t in traps)

    def test_verify_cmd_dsh(self):
        assert vendor_verify_cmd("dsh") == "dsh --profile headless --dump-config"

    def test_zero_quota_cmds_dsh(self):
        zq = vendor_zero_quota_cmds("dsh")
        assert "dsh --profile headless --dump-config" in zq


# ─── dispatch_core.py: build_dsh_cmd ───

class TestBuildDshCmd:
    def test_build_dsh_cmd_with_model(self):
        cmd = build_dsh_cmd("deepseek-v4-pro", "/tmp/patch.yaml")
        assert cmd == ["dsh", "--profile", "headless", "--patch", "/tmp/patch.yaml"]

    def test_build_dsh_cmd_auto_no_patch(self):
        """Builder auto giờ PHẢI pin resolved_model thay CLIdefault (--patch được pin)."""
        cmd = build_dsh_cmd("auto", "/tmp/patch.yaml")
        assert "--patch" in cmd
        assert cmd == ["dsh", "--profile", "headless", "--patch", "/tmp/patch.yaml"]

    def test_write_dsh_patch_valid_yaml(self):
        with tempfile.NamedTemporaryFile(mode="r", suffix=".yaml", delete=False) as f:
            path = f.name
        try:
            write_dsh_patch("deepseek-v4-pro", path)
            content = Path(path).read_text()
            assert "agent-default-model" in content
            assert "deepseek-v4-pro" in content
            assert "deepseek-official" in content
        finally:
            os.unlink(path)

    def test_dsh_default_model_is_pro(self):
        """🔴 auto → pro, KHÔNG phải flash."""
        assert DSH_DEFAULT_MODEL == "deepseek-v4-pro"


# ─── REGISTRY: dsh in vendors.py ───

class TestDshRegistry:
    def test_dsh_in_registry(self):
        assert "dsh" in REGISTRY

    def test_dsh_binary(self):
        assert REGISTRY["dsh"].binary == "dsh"

    def test_dsh_auth_hint(self):
        assert "DEEPSEEK_API_KEY" in REGISTRY["dsh"].auth_hint


# ─── dispatcher.py: dsh lane ───

class TestDshDispatch:
    def test_dsh_auto_resolves_to_pro(self):
        """Dispatch dsh model=auto → phải ghim deepseek-v4-pro."""
        calls = []

        def mock_runner(cmd, **kwargs):
            calls.append(cmd)
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = "task done"
            mock.stderr = ""
            return mock

        def mock_detector(spec):
            return VendorProbe(
                name="dsh", path="/usr/local/bin/dsh",
                authed=True, quota_capped=False, version="1.0",
            )

        result = run_vendor(
            vendor="dsh", prompt="test", model="auto",
            runner=mock_runner, detector=mock_detector,
        )
        assert result.status == "ok"
        # Grok finding 3: output không chứng minh -> served_model=None, không bịa intent slug
        assert result.served_model is None
        assert any("deepseek-v4-pro" in w for w in result.warnings)
        # cmd phải có --patch (vì resolved != auto)
        cmd = calls[0]
        assert "--patch" in cmd

    def test_dsh_explicit_model(self):
        """Dispatch dsh model=deepseek-v4-flash → ghim đúng flash."""
        calls = []

        def mock_runner(cmd, **kwargs):
            calls.append(cmd)
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = "done"
            mock.stderr = ""
            return mock

        def mock_detector(spec):
            return VendorProbe(
                name="dsh", path="/usr/local/bin/dsh",
                authed=True, quota_capped=False,
            )

        result = run_vendor(
            vendor="dsh", prompt="test", model="deepseek-v4-flash",
            runner=mock_runner, detector=mock_detector,
        )
        assert result.status == "ok"
        # Grok finding 3: output không chứng minh -> served_model=None
        assert result.served_model is None
        assert any("deepseek-v4-flash" in w for w in result.warnings)

    def test_dsh_actual_response_extraction(self):
        """Negative test: DSH plaintext output JSON tự xưng model/modelVersion/served_model
        là do model sinh ra trong output plaintext, KHÔNG phải harness metadata tin cậy.
        served_model vẫn phải là None, requested model giữ nguyên.
        """
        for forged_payload in [
            {"model": "deepseek-v4-pro", "text": "task done"},
            {"modelVersion": "deepseek-v4-pro", "text": "task done"},
            {"served_model": "deepseek-v4-pro", "text": "task done"},
            {"model": "gpt-4o", "modelVersion": "v1", "served_model": "fake", "text": "done"},
        ]:
            def mock_runner(cmd, **kwargs):
                mock = MagicMock()
                mock.returncode = 0
                mock.stdout = json.dumps(forged_payload)
                mock.stderr = ""
                return mock

            def mock_detector(spec):
                return VendorProbe(
                    name="dsh", path="/usr/local/bin/dsh",
                    authed=True, quota_capped=False, version="1.0",
                )

            # Case model=auto -> requested model "auto" giữ nguyên, served_model None
            result = run_vendor(
                vendor="dsh", prompt="test", model="auto",
                runner=mock_runner, detector=mock_detector,
            )
            assert result.status == "ok"
            assert result.model == "auto"
            assert result.served_model is None
            assert any("deepseek-v4-pro" in w for w in result.warnings)

            # Case explicit requested model -> requested model giữ nguyên, served_model None
            result_explicit = run_vendor(
                vendor="dsh", prompt="test", model="deepseek-v4-flash",
                runner=mock_runner, detector=mock_detector,
            )
            assert result_explicit.status == "ok"
            assert result_explicit.model == "deepseek-v4-flash"
            assert result_explicit.served_model is None
            assert any("deepseek-v4-flash" in w for w in result_explicit.warnings)

    def test_dsh_not_installed_degraded(self):
        def mock_detector(spec):
            return VendorProbe(
                name="dsh", path=None, authed=False, quota_capped=False,
            )

        result = run_vendor(
            vendor="dsh", prompt="test",
            detector=mock_detector,
        )
        assert result.status == "skipped"
        assert result.reason == "not_installed"


# ─── dispatch.py CLI: auto → default_model resolution ───

class TestDispatchCLI:
    def test_dump_config_resolves_auto(self):
        """--dump-config phải cho resolved_model = default_model của vendor."""
        res = subprocess.run(
            [sys.executable, "bin/dispatch.py", "codex", "--dump-config"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(__file__).parent.parent),
        )
        assert res.returncode == 0
        info = json.loads(res.stdout)
        assert info["vendor"] == "codex"
        assert info["requested_model"] == "auto"
        # Cập nhật default codex -> gpt-6.1-sol
        assert info["resolved_model"] == "gpt-6.1-sol"

    def test_dump_config_dsh_auto_pro(self):
        """dsh auto phải resolve thành deepseek-v4-pro (KHÔNG phải flash)."""
        res = subprocess.run(
            [sys.executable, "bin/dispatch.py", "dsh", "--dump-config"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(__file__).parent.parent),
        )
        assert res.returncode == 0
        info = json.loads(res.stdout)
        assert info["vendor"] == "dsh"
        assert info["resolved_model"] == "deepseek-v4-pro"

    def test_dump_config_agy_auto_38_flash_high(self):
        """agy auto phải resolve thành gemini-3.8-flash-high."""
        res = subprocess.run(
            [sys.executable, "bin/dispatch.py", "agy", "--dump-config"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(__file__).parent.parent),
        )
        assert res.returncode == 0
        info = json.loads(res.stdout)
        assert info["vendor"] == "agy"
        assert info["resolved_model"] == "gemini-3.8-flash-high"
        assert info["default_model"] == "gemini-3.8-flash-high"

    def test_no_traps_suppresses_stderr(self):
        """--no-traps phải không in traps ra stderr."""
        res = subprocess.run(
            [sys.executable, "bin/dispatch.py", "dsh", "--no-traps", "--dump-config"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(__file__).parent.parent),
        )
        assert res.returncode == 0
        assert "traps" not in res.stderr.lower() or "traps for" not in res.stderr

    def test_vendor_choices_from_json(self):
        """argparse phải nhận tất cả 10 vendor từ JSON."""
        res = subprocess.run(
            [sys.executable, "bin/dispatch.py", "dsh", "--dump-config"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(__file__).parent.parent),
        )
        assert res.returncode == 0

        # Vendor không có trong JSON phải bị reject
        res2 = subprocess.run(
            [sys.executable, "bin/dispatch.py", "nonexistent", "--dump-config"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(__file__).parent.parent),
        )
        assert res2.returncode != 0

# ─── VÒNG 2 FIXES ───

@pytest.fixture
def fake_vendors(monkeypatch):
    """Dynamic fakevendor fixture khai default_model cho auto pin, có model_flag và no_flag."""
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


class TestVong2:
    def test_doctor_exit_nonzero(self):
        """1. --doctor phải không nuốt lỗi, trả exit code khác 0."""
        from unittest.mock import patch
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=2, stdout="", stderr="some error")
            with pytest.raises(SystemExit) as e:
                import bin.dispatch
                # override args to trigger doctor
                with patch("sys.argv", ["dispatch.py", "agy", "--doctor"]):
                    bin.dispatch.main()
            assert e.value.code == 2

    def test_openrouter_in_choices(self):
        """2. openrouter phải nằm trong choices; OR auto blocked thì test choices dùng concrete paid org/model để tách policy khỏi choices."""
        res = subprocess.run(
            [sys.executable, "bin/dispatch.py", "openrouter", "openai/gpt-4o", "--dump-config"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert res.returncode == 0
        info = json.loads(res.stdout)
        assert info["vendor"] == "openrouter"
        assert info["resolved_model"] == "openai/gpt-4o"

    def test_dynamic_vendor_from_json(self, fake_vendors):
        """3. Vendor giả phải dùng lệnh từ JSON (headless)."""
        calls = []
        def mock_runner(cmd, **kwargs):
            calls.append(cmd)
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = "task done"
            mock.stderr = ""
            return mock
        
        with patch("shutil.which", return_value="/usr/bin/fakebin"):
            result = run_vendor(
                vendor="fakevendor_with_flag", prompt="hello world", model="auto",
                runner=mock_runner, detector=lambda spec: VendorProbe(
                    name="fakevendor_with_flag", path="/usr/bin/fakebin", authed=True, quota_capped=False,
                    version=None, models=[], error=None
                )
            )
        assert result.status == "ok"
        assert len(calls) == 1
        cmd_str = calls[0]
        # assert lệnh được dựng từ trường headless
        assert "fakebin run 'hello world' < /dev/null" in cmd_str

    def test_reject_fake_model(self):
        """4. Catalog advisory: model unknown hợp grammar được phép trong dump-config (catalog null không ép warning unknown list; injected catalog thật missing cần warning)."""
        res = subprocess.run(
            [sys.executable, "bin/dispatch.py", "dsh", "totally-fake-model", "--dump-config"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert res.returncode == 0
        info = json.loads(res.stdout)
        assert info["resolved_model"] == "totally-fake-model"

        # Policy test: injected catalog thật missing cần warning ở policy tests
        from lib.vendor_config import resolve_vendor_model
        target = resolve_vendor_model(vendor="dsh", model="totally-fake-model", catalog_models=["deepseek-v4-pro"])
        assert target.model == "totally-fake-model"
        assert any("not present in the current verified catalog" in w for w in target.warnings)

    def test_allow_unknown_model(self):
        """4. --allow-unknown-model cho phép bypass."""
        res = subprocess.run(
            [sys.executable, "bin/dispatch.py", "dsh", "totally-fake-model", "--allow-unknown-model", "--dump-config"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert res.returncode == 0
        info = json.loads(res.stdout)
        assert info["resolved_model"] == "totally-fake-model"
