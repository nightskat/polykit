from __future__ import annotations
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from lib.states import VendorProbe

@dataclass(frozen=True)
class VendorSpec:
    name: str
    binary: str | None  # None = vendor API-key (không có CLI binary, vd OpenRouter)
    auth_hint: str
    version_cmd: list[str] | None
    auth_check_cmd: list[str] | None
    # Khi không có auth_check_cmd: True = coi như đã auth (policy tường minh,
    # chỉ dùng cho host `claude` chạy bên trong Claude Code); False = chưa rõ auth
    # → installed_not_authed (không mark ready chỉ vì binary tồn tại).
    assume_authed: bool = False
    # Vendor API-key: env chứa key. binary=None → detect theo key, không theo which().
    api_key_env: list[str] | None = None

REGISTRY: dict[str, VendorSpec] = {
    "codex": VendorSpec(
        name="codex",
        binary="codex",
        auth_hint="chạy `codex login`",
        version_cmd=["codex", "--version"],
        auth_check_cmd=["codex", "login", "status"],
    ),
    "gemini": VendorSpec(
        name="gemini",
        binary="gemini",
        auth_hint="chạy `gemini` rồi /auth",
        version_cmd=["gemini", "--version"],
        auth_check_cmd=["gemini", "--list-sessions"],
    ),
    "claude": VendorSpec(
        name="claude",
        binary="claude",
        auth_hint="đã auth qua Claude Code (host)",
        version_cmd=["claude", "--version"],
        auth_check_cmd=None,
        assume_authed=True,
    ),
    "grok": VendorSpec(
        name="grok",
        binary="grok",
        auth_hint="chạy `grok` để auth",
        version_cmd=["grok", "--version"],
        auth_check_cmd=["grok", "inspect"],
    ),
    "openrouter": VendorSpec(
        name="openrouter",
        binary=None,  # hosted API, không có CLI
        auth_hint="lấy key free tại openrouter.ai/keys rồi `export OPENROUTER_API_KEY=...`",
        version_cmd=None,
        auth_check_cmd=None,
        api_key_env=["OPENROUTER_API_KEY", "OR_API_KEY"],
    ),
}

def _detect_api_key_vendor(spec: VendorSpec) -> VendorProbe:
    """Vendor API-key (binary=None): hosted service nên KHÔNG bao giờ not_installed —
    ready iff có key, else installed_not_authed. path = sentinel non-None."""
    key = None
    if spec.name == "openrouter":
        from lib.openrouter import get_or_key
        key = get_or_key()
    else:
        for env in (spec.api_key_env or []):
            if os.environ.get(env):
                key = os.environ[env]
                break
    return VendorProbe(
        name=spec.name,
        path=f"api:{spec.name}",  # sentinel: không phải not_installed
        authed=bool(key),
        quota_capped=False,
        version=None,
        models=[],
        error=None,
    )

def detect(spec: VendorSpec, which=shutil.which, runner=subprocess.run) -> VendorProbe:
    if spec.binary is None:
        return _detect_api_key_vendor(spec)
    path_str = which(spec.binary)
    if path_str is None:
        return VendorProbe(
            name=spec.name,
            path=None,
            authed=False,
            quota_capped=False,
            version=None,
            models=[],
            error=None
        )
    
    abs_path = str(Path(path_str).resolve())
    version = None
    authed = False
    error = None

    try:
        if spec.version_cmd:
            cmd = [abs_path] + spec.version_cmd[1:]
            res = runner(cmd, capture_output=True, text=True, timeout=10)
            # Chỉ nhận version khi lệnh thành công — tránh dùng stderr lỗi làm version.
            if res.returncode == 0:
                version = res.stdout.strip() or None

        if spec.auth_check_cmd:
            cmd = [abs_path] + spec.auth_check_cmd[1:]
            res = runner(cmd, capture_output=True, text=True, timeout=10)
            authed = (res.returncode == 0)
        else:
            # Không có cách kiểm auth: chỉ ready nếu policy assume_authed (host claude).
            authed = spec.assume_authed
    except subprocess.TimeoutExpired:
        error = "timeout"
        authed = False
    except (OSError, subprocess.SubprocessError) as e:
        # Path chết sau which(), symlink hỏng, permission... → mã lỗi ổn định.
        error = f"{type(e).__name__}: {e}"
        authed = False

    return VendorProbe(
        name=spec.name,
        path=abs_path,
        authed=authed,
        quota_capped=False,
        version=version,
        models=[],
        error=error
    )

def detect_all(specs=None, which=shutil.which, runner=subprocess.run) -> list[VendorProbe]:
    if specs is None:
        specs = list(REGISTRY.values())
    return [detect(spec, which=which, runner=runner) for spec in specs]
