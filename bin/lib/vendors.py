from __future__ import annotations
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from lib.states import VendorProbe

@dataclass(frozen=True)
class VendorSpec:
    name: str
    binary: str
    auth_hint: str
    version_cmd: list[str] | None
    auth_check_cmd: list[str] | None
    # Khi không có auth_check_cmd: True = coi như đã auth (policy tường minh,
    # chỉ dùng cho host `claude` chạy bên trong Claude Code); False = chưa rõ auth
    # → installed_not_authed (không mark ready chỉ vì binary tồn tại).
    assume_authed: bool = False

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
}

def detect(spec: VendorSpec, which=shutil.which, runner=subprocess.run) -> VendorProbe:
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
