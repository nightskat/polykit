"""Tests cho Lô 5: OpenCode/Hermes registry, doctor state machine, codex JSON parser, ZDR expiry.

Đảm bảo:
- Registry opencode: binary Path.home/.opencode/bin/opencode (absolute), version cmd --version không auth.
- Registry hermes: which hermes, version cmd --version không auth.
- Không gọi auth dump / config credentials, không probe task inference.
- Không suy ready từ catalog: không có verified auth cmd -> auth_unverified (authed=None) thay vì not_authed hay ready.
- Parser JSON riêng cho codex debug models, fixture mô phỏng shape thật, fail explicit không invent.
- Hai adapter meta provider/quota_group = opencode-go.
- Doctor additive state metadata: probe_checked_at, source, catalog_source, stale, error.
- DeepSeek ZDR expiry 2026-10-31: cảnh báo trước / đúng ngày / sau ngày, renewal chưa xác minh phải cảnh báo.
  Không dựa ngày hiện tại cố định. Config expiry không được âm thầm gia hạn.
- Giữ error stderr/BUG15 và vendor cũ.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
import pytest

from lib.states import VendorProbe, VendorState, classify
from lib.vendors import REGISTRY, VendorSpec, detect, parse_codex_models, parse_models
from doctor import check_zdr_expiry, run_doctor, render_table


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ==============================================================================
# 1. Registry specs: OpenCode & Hermes
# ==============================================================================

def test_registry_contains_opencode_and_hermes():
    assert "opencode" in REGISTRY
    assert "hermes" in REGISTRY


def test_opencode_binary_is_absolute_path_under_home():
    spec = REGISTRY["opencode"]
    assert spec.binary == str(Path.home() / ".opencode" / "bin" / "opencode")
    assert Path(spec.binary).is_absolute()
    assert spec.provider == "opencode-go"
    assert spec.quota_group == "opencode-go"


def test_hermes_binary_is_which_lookup():
    spec = REGISTRY["hermes"]
    assert spec.binary == "hermes"
    assert not Path(spec.binary).is_absolute()
    assert spec.provider == "opencode-go"
    assert spec.quota_group == "opencode-go"


def test_version_cmd_does_not_auth_and_no_credential_dump_cmd():
    for name in ("opencode", "hermes"):
        spec = REGISTRY[name]
        # Version cmd chỉ là --version
        assert spec.version_cmd is not None
        assert "--version" in spec.version_cmd
        # CẤM gọi auth dump, config credentials hoặc probe task inference
        assert spec.auth_check_cmd is None
        assert spec.assume_authed is None


# ==============================================================================
# 2. Missing binary -> not_installed
# ==============================================================================

def test_opencode_missing_binary_is_not_installed():
    p = detect(REGISTRY["opencode"], which=lambda b: None)
    assert p.path is None
    assert p.authed is False
    assert classify(p) == VendorState.NOT_INSTALLED


def test_hermes_missing_binary_is_not_installed():
    p = detect(REGISTRY["hermes"], which=lambda b: None)
    assert p.path is None
    assert p.authed is False
    assert classify(p) == VendorState.NOT_INSTALLED


# ==============================================================================
# 3. Auth unverified (authed=None) & Doctor không ready giả
# ==============================================================================

def test_installed_opencode_is_auth_unverified_not_not_authed_or_ready():
    def runner(cmd, **kw):
        if "--version" in cmd:
            return FakeCompleted(returncode=0, stdout="opencode 1.0.0")
        if "models" in cmd:
            return FakeCompleted(returncode=0, stdout="opencode-go/deepseek-v4.1-flash\n")
        return FakeCompleted(returncode=0)

    p = detect(
        REGISTRY["opencode"],
        which=lambda b: "/fake/home/.opencode/bin/opencode",
        runner=runner,
    )
    assert p.path == "/fake/home/.opencode/bin/opencode"
    assert p.version == "opencode 1.0.0"
    # Không có verified auth cmd -> authed=None (auth_unverified), KHÔNG PHẢI False (not_authed) hay True (ready)
    assert p.authed is None
    assert classify(p) == VendorState.AUTH_UNVERIFIED
    assert classify(p) != VendorState.READY
    assert classify(p) != VendorState.INSTALLED_NOT_AUTHED


def test_installed_hermes_is_auth_unverified_not_not_authed_or_ready():
    def runner(cmd, **kw):
        if "--version" in cmd:
            return FakeCompleted(returncode=0, stdout="hermes 0.5.0")
        return FakeCompleted(returncode=0)

    p = detect(
        REGISTRY["hermes"],
        which=lambda b: "/usr/local/bin/hermes",
        runner=runner,
    )
    assert p.path == "/usr/local/bin/hermes"
    assert p.version == "hermes 0.5.0"
    assert p.authed is None
    assert classify(p) == VendorState.AUTH_UNVERIFIED
    assert classify(p) != VendorState.READY
    assert classify(p) != VendorState.INSTALLED_NOT_AUTHED


def test_opencode_does_not_infer_ready_from_catalog():
    """Catalog có 28 model cũng KHÔNG được suy thành ready."""
    catalog_output = "\n".join([
        "opencode-go/deepseek-v4.1-flash",
        "opencode-go/glm-5.3-flash",
        "opencode-go/mimo-v2.6-flash",
    ])
    def runner(cmd, **kw):
        if "--version" in cmd:
            return FakeCompleted(returncode=0, stdout="opencode 1.0.0")
        if "models" in cmd:
            return FakeCompleted(returncode=0, stdout=catalog_output)
        return FakeCompleted(returncode=0)

    p = detect(
        REGISTRY["opencode"],
        which=lambda b: "/fake/home/.opencode/bin/opencode",
        runner=runner,
    )
    assert len(p.models) == 3
    # Mặc dù catalog đầy đủ, authed vẫn là None (auth_unverified) — không suy ready từ catalog
    assert p.authed is None
    assert classify(p) == VendorState.AUTH_UNVERIFIED


# ==============================================================================
# 4. Codex catalog JSON parser riêng
# ==============================================================================

CODEX_DEBUG_MODELS_FIXTURE = json.dumps({
    "models": [
        {
            "slug": "gpt-6.1-sol",
            "display_name": "GPT-6.1-Sol",
            "description": "Latest workhorse model for coding and everyday work.",
            "default_reasoning_level": "low",
            "supported_reasoning_levels": [
                {"effort": "low", "description": "Fast"},
                {"effort": "medium", "description": "Balanced"},
                {"effort": "high", "description": "Greater"},
            ],
            "shell_type": "unified_exec",
            "visibility": "list",
            "supported_in_api": True,
            "priority": 1,
        },
        {
            "slug": "gpt-6-astra",
            "display_name": "GPT-6-Astra",
            "description": "Astra flagship model",
            "default_reasoning_level": "low",
            "supported_reasoning_levels": [{"effort": "low"}],
        },
        {
            "slug": "gpt-6-sol",
            "display_name": "GPT-6-Sol",
            "default_reasoning_level": "medium",
        },
    ]
})


def test_parse_codex_models_valid_fixture():
    slugs = parse_codex_models(CODEX_DEBUG_MODELS_FIXTURE)
    assert slugs == ["gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol"]


def test_parse_codex_models_uses_json_not_raw_token_split():
    # If parse_models (raw token regex) is used on JSON, it fails or parses mangled tokens
    raw_slugs = parse_models(CODEX_DEBUG_MODELS_FIXTURE)
    json_slugs = parse_codex_models(CODEX_DEBUG_MODELS_FIXTURE)
    assert json_slugs == ["gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol"]
    assert raw_slugs != json_slugs


def test_parse_codex_models_fails_explicit_on_invalid_or_unknown_shape():
    # 1. Empty string
    with pytest.raises(ValueError, match="empty"):
        parse_codex_models("")

    # 2. Non-JSON string
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_codex_models("not json content")

    # 3. JSON array instead of dict
    with pytest.raises(ValueError, match="expected JSON object"):
        parse_codex_models(json.dumps(["gpt-6.1-sol"]))

    # 4. Dict missing "models" key
    with pytest.raises(KeyError, match="missing 'models' key"):
        parse_codex_models(json.dumps({"data": [{"slug": "gpt-6.1-sol"}]}))

    # 5. "models" is not a list
    with pytest.raises(ValueError, match="'models' field must be a list"):
        parse_codex_models(json.dumps({"models": "gpt-6.1-sol"}))

    # 6. Item in models list missing "slug"
    with pytest.raises(KeyError, match="missing required key 'slug'"):
        parse_codex_models(json.dumps({"models": [{"name": "gpt-6.1-sol"}]}))

    # 7. Item with empty slug
    with pytest.raises(ValueError, match="invalid slug"):
        parse_codex_models(json.dumps({"models": [{"slug": "   "}]}))


def test_codex_detect_uses_parse_codex_models():
    def runner(cmd, **kw):
        if "--version" in cmd:
            return FakeCompleted(returncode=0, stdout="codex 0.1.0")
        if "login" in cmd and "status" in cmd:
            return FakeCompleted(returncode=0, stdout="Logged in")
        if "debug" in cmd and "models" in cmd:
            return FakeCompleted(returncode=0, stdout=CODEX_DEBUG_MODELS_FIXTURE)
        return FakeCompleted(returncode=0)

    p = detect(REGISTRY["codex"], which=lambda b: "/usr/local/bin/codex", runner=runner)
    assert p.authed is True
    assert p.models == ["gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol"]
    assert p.error is None


# ==============================================================================
# 5. Catalog empty & transport timeout
# ==============================================================================

def test_catalog_empty_when_models_cmd_returns_empty():
    def runner(cmd, **kw):
        if "--version" in cmd:
            return FakeCompleted(returncode=0, stdout="agy 1.0.0")
        if "models" in cmd:
            return FakeCompleted(returncode=0, stdout="")
        return FakeCompleted(returncode=0)

    p = detect(REGISTRY["agy"], which=lambda b: "/usr/local/bin/agy", runner=runner)
    assert p.models == []
    assert p.error == "catalog_empty"


def test_transport_timeout_in_detect_preserves_error():
    # 1. Version command timeout
    def runner_version_timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=10)

    p_hermes = detect(REGISTRY["hermes"], which=lambda b: "/bin/hermes", runner=runner_version_timeout)
    assert p_hermes.error is not None
    assert "timeout" in p_hermes.error.lower()

    # 2. Models command timeout (opencode)
    def runner_models_timeout(cmd, **kw):
        if "--version" in cmd:
            return FakeCompleted(returncode=0, stdout="opencode 1.0.0")
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=10)

    p_opencode = detect(
        REGISTRY["opencode"],
        which=lambda b: "/fake/home/.opencode/bin/opencode",
        runner=runner_models_timeout,
    )
    assert p_opencode.error is not None
    assert "timeout" in p_opencode.error.lower()
    assert p_opencode.authed is None  # vẫn giữ unverified, không crash


# ==============================================================================
# 6. DeepSeek ZDR expiry 2026-10-31: trước, ngày, sau, và renewal cảnh báo
# ==============================================================================

def test_zdr_expiry_truoc_ngay():
    zdr = {
        "supported": True,
        "expiry": "2026-10-31",
        "permanent": False,
        "renewal_verified": False,
    }
    # Ngày kiểm tra: 25/10/2026 (trước 2026-10-31 6 ngày)
    res = check_zdr_expiry(zdr, now="2026-10-25")
    assert res["status"] == "expiring_soon"
    assert res["days_left"] == 6
    assert "sắp hết hạn" in res["warning"]
    assert "còn 6 ngày" in res["warning"]
    assert "gia hạn chưa được xác minh" in res["warning"]


def test_zdr_expiry_dung_ngay():
    zdr = {
        "supported": True,
        "expiry": "2026-10-31",
        "permanent": False,
        "renewal_verified": False,
    }
    # Đúng ngày 2026-10-31
    res = check_zdr_expiry(zdr, now="2026-10-31")
    assert res["status"] == "expires_today"
    assert res["days_left"] == 0
    assert "hết hạn hôm nay" in res["warning"]
    assert "gia hạn chưa được xác minh" in res["warning"]


def test_zdr_expiry_sau_ngay():
    zdr = {
        "supported": True,
        "expiry": "2026-10-31",
        "permanent": False,
        "renewal_verified": False,
    }
    # Sau ngày: 01/11/2026 (quá hạn 1 ngày)
    res = check_zdr_expiry(zdr, now="2026-11-01")
    assert res["status"] == "expired"
    assert res["days_left"] == -1
    assert "đã hết hạn" in res["warning"]
    assert "quá hạn 1 ngày" in res["warning"]
    assert "gia hạn chưa được xác minh" in res["warning"]


def test_zdr_expiry_renewal_da_xac_minh_khong_canh_bao_chua_xac_minh():
    zdr = {
        "supported": True,
        "expiry": "2026-10-31",
        "permanent": False,
        "renewal_verified": True,
    }
    res = check_zdr_expiry(zdr, now="2026-10-25")
    assert "gia hạn chưa được xác minh" not in res["warning"]


def test_zdr_config_expiry_khong_am_tham_gia_han():
    """Config ghi expiry nào thì dùng đúng expiry đó, không tự động gia hạn thành ngày tương lai."""
    zdr = {
        "supported": True,
        "expiry": "2026-10-31",
        "permanent": False,
    }
    res = check_zdr_expiry(zdr, now="2026-12-01")
    # Vẫn giữ nguyên expiry=2026-10-31 và báo expired, không tự gia hạn
    assert res["expiry"] == "2026-10-31"
    assert res["status"] == "expired"


def test_zdr_tampered2027_date11_01_van_expired():
    """Grok finding 6: config tamper ngày expiry 2027 và claim renewal/permanent
    thì vẫn bị kẹp về min(config, 2026-10-31), date 2026-11-01 vẫn expired."""
    zdr = {
        "supported": True,
        "expiry": "2027-12-31",
        "renewal_verified": True,
        "permanent": True,
    }
    res = check_zdr_expiry(zdr, now="2026-11-01")
    assert res["status"] == "expired"
    assert res["expiry"] == "2026-10-31"
    assert res["days_left"] == -1
    assert "đã hết hạn" in res["warning"]
    assert "quá hạn 1 ngày" in res["warning"]
    assert "2026-10-31" in res["warning"]
    # Renewal claim vượt mốc verified không được công nhận
    assert res["renewal_verified"] is False


def test_zdr_earlier_expiry_giu():
    """Earlier expiry (< 2026-10-31) được giữ nguyên qua min(config, 2026-10-31)."""
    zdr = {
        "supported": True,
        "expiry": "2026-10-15",
        "permanent": False,
    }
    res = check_zdr_expiry(zdr, now="2026-10-10")
    assert res["expiry"] == "2026-10-15"
    assert res["days_left"] == 5
    assert res["status"] == "expiring_soon"
    assert "2026-10-15" in res["warning"]
    assert "còn 5 ngày" in res["warning"]


def test_zdr_invalid_bool_dict_missing_khong_crash_tra_unverified_failclosed():
    """Expiry invalid, bool, dict, bad string hoặc missing trả warning unverified failclosed
    không làm crash doctor."""
    # 1. bool
    res_bool = check_zdr_expiry({"expiry": True}, now="2026-10-25")
    assert res_bool["status"] == "unverified"
    assert "unverified" in res_bool["warning"]
    assert "failclosed" in res_bool["warning"]

    # 2. dict
    res_dict = check_zdr_expiry({"expiry": {"date": "2026-10-31"}}, now="2026-10-25")
    assert res_dict["status"] == "unverified"
    assert "unverified" in res_dict["warning"]
    assert "failclosed" in res_dict["warning"]

    # 3. bad string
    res_bad = check_zdr_expiry({"expiry": "not-a-date"}, now="2026-10-25")
    assert res_bad["status"] == "unverified"
    assert "unverified" in res_bad["warning"]
    assert "failclosed" in res_bad["warning"]

    # 4. missing expiry key
    res_missing = check_zdr_expiry({}, now="2026-10-25")
    assert res_missing["status"] == "unverified"
    assert "unverified" in res_missing["warning"]
    assert "failclosed" in res_missing["warning"]

    # 5. non-dict input
    res_non_dict = check_zdr_expiry(None, now="2026-10-25")
    assert res_non_dict["status"] == "unverified"
    assert "unverified" in res_non_dict["warning"]
    assert "failclosed" in res_non_dict["warning"]


# ==============================================================================
# 7. Doctor additive state metadata sau build_state
# ==============================================================================

def test_doctor_additive_metadata_and_adapter_meta(monkeypatch):
    probes = [
        VendorProbe(
            name="opencode",
            path="/fake/.opencode/bin/opencode",
            authed=None,
            quota_capped=False,
            version="1.0.0",
            models=["opencode-go/deepseek-v4.1-flash"],
            error=None,
        ),
        VendorProbe(
            name="hermes",
            path="/usr/local/bin/hermes",
            authed=None,
            quota_capped=False,
            version="0.5.0",
            models=[],
            error=None,
        ),
    ]

    monkeypatch.setattr("doctor.write_state", lambda s, path=None: path)
    monkeypatch.setattr("doctor.read_evidence", lambda limit=20, path=None: [])

    now_iso = "2026-10-25T10:00:00+00:00"
    state = run_doctor(probes=probes, now=now_iso)

    # 1. State machine không ready giả
    assert state["vendors"]["opencode"]["state"] == "auth_unverified"
    assert state["vendors"]["hermes"]["state"] == "auth_unverified"

    # 2. Additive metadata
    for name in ("opencode", "hermes"):
        v = state["vendors"][name]
        assert v["probe_checked_at"] == now_iso
        assert v["source"] == "cli"
        assert v["stale"] is False
        assert v["provider"] == "opencode-go"
        assert v["quota_group"] == "opencode-go"

    assert state["vendors"]["opencode"]["catalog_source"] == "models_cmd"
    assert state["vendors"]["hermes"]["catalog_source"] == "none"

    # 3. ZDR warning được gắn vào state (cả opencode và hermes)
    assert state["vendors"]["opencode"]["zdr_status"] == "expiring_soon"
    assert "zdr_warning" in state["vendors"]["opencode"]
    assert state["vendors"]["hermes"]["zdr_status"] == "expiring_soon"
    assert "zdr_warning" in state["vendors"]["hermes"]
    assert any("DeepSeek ZDR" in w for w in state.get("warnings", []))


def test_doctor_zdr_chi_ap_dung_provider_opencode_go_khong_gan_dsh(monkeypatch):
    """Metadata privacy nguồn Go chỉ áp dụng provider opencode-go (opencode, hermes);
    KHÔNG gán ZDR Go/no-train cho DSH DeepSeek official chỉ vì tên họ model
    (doctor fallback cũ cho dsh không có source evidence).
    Giữ warnings Go cho cả hermes và opencode."""
    probes = [
        VendorProbe(
            name="opencode",
            path="/fake/.opencode/bin/opencode",
            authed=None,
            quota_capped=False,
            version="1.0.0",
            models=["opencode-go/deepseek-v4.1-flash"],
            error=None,
        ),
        VendorProbe(
            name="hermes",
            path="/usr/local/bin/hermes",
            authed=None,
            quota_capped=False,
            version="0.5.0",
            models=["opencode-go/deepseek-v4.1-flash"],
            error=None,
        ),
        VendorProbe(
            name="dsh",
            path="/usr/local/bin/dsh",
            authed=True,
            quota_capped=False,
            version="1.0.0",
            models=["deepseek-v4-pro"],
            error=None,
        ),
    ]

    monkeypatch.setattr("doctor.write_state", lambda s, path=None: path)
    monkeypatch.setattr("doctor.read_evidence", lambda limit=20, path=None: [])

    now_iso = "2026-10-25T10:00:00+00:00"
    state = run_doctor(probes=probes, now=now_iso)

    # 1. opencode và hermes (provider opencode-go) đều có ZDR warning
    assert state["vendors"]["opencode"]["zdr_status"] == "expiring_soon"
    assert "zdr_warning" in state["vendors"]["opencode"]

    assert state["vendors"]["hermes"]["zdr_status"] == "expiring_soon"
    assert "zdr_warning" in state["vendors"]["hermes"]

    # Warnings tổng của state chứa cả [opencode] và [hermes]
    assert any("[opencode] DeepSeek ZDR" in w for w in state.get("warnings", []))
    assert any("[hermes] DeepSeek ZDR" in w for w in state.get("warnings", []))

    # 2. dsh (DeepSeek official) KHÔNG bị gán ZDR Go / no-train
    assert "zdr_status" not in state["vendors"]["dsh"]
    assert "zdr_warning" not in state["vendors"]["dsh"]
    assert "zdr" not in state["vendors"]["dsh"]
    assert not any("[dsh]" in w and "DeepSeek ZDR" in w for w in state.get("warnings", []))


def test_doctor_render_table_contains_zdr_and_auth_unverified():
    state = {
        "schema_version": 1,
        "generated_at": "2026-10-25T10:00:00+00:00",
        "vendors": {
            "opencode": {
                "state": "auth_unverified",
                "cli_path": "/fake/.opencode/bin/opencode",
                "cli_version": "1.0.0",
                "auth_hint": "kiểm tra credentials Go tại ~/.opencode",
                "zdr_warning": "DeepSeek ZDR sắp hết hạn vào 2026-10-31 (còn 6 ngày)",
            }
        }
    }
    table = render_table(state)
    assert "opencode" in table
    assert "auth_unverified" in table
    assert "⚠️ ZDR: DeepSeek ZDR sắp hết hạn" in table


# ==============================================================================
# 8. Giữ vendor cũ và stderr / BUG-15
# ==============================================================================

def test_vendor_cu_van_con_nguyen():
    for old_vendor in ("codex", "gemini", "claude", "grok", "agy", "openrouter", "dsh"):
        assert old_vendor in REGISTRY


def test_bug13_stderr_giu_nguyen_khi_probe_unverified():
    """BUG-13: giữ stderr khi probe unverified."""
    spec = VendorSpec(
        name="test_v",
        binary="test_v",
        auth_hint="hint",
        version_cmd=["test_v", "--version"],
        auth_check_cmd=["test_v", "auth", "check"],
        auth_check_authoritative=False,
    )
    def runner(cmd, **kw):
        if "--version" in cmd:
            return FakeCompleted(returncode=0, stdout="1.0")
        return FakeCompleted(returncode=1, stderr="Lỗi kết nối máy chủ xác thực: Connection timed out")

    p = detect(spec, which=lambda b: "/bin/test_v", runner=runner)
    assert p.authed is None
    assert p.error is not None
    assert "Connection timed out" in p.error
