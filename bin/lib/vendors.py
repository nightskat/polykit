from __future__ import annotations
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from lib.states import VendorProbe
from lib.quota_error import is_quota_error

@dataclass(frozen=True)
class VendorSpec:
    name: str
    binary: str | None  # None = vendor API-key (không có CLI binary, vd OpenRouter)
    auth_hint: str
    version_cmd: list[str] | None
    auth_check_cmd: list[str] | None
    # Một số lệnh "probe" là catalog/session phụ, không phải auth status. Khi
    # chúng lỗi, phải báo unverified thay vì kết luận người dùng đã logout.
    auth_check_authoritative: bool = True
    # Khi không có auth_check_cmd: True = coi như đã auth (policy tường minh,
    # chỉ dùng cho host `claude` chạy bên trong Claude Code); False = chưa rõ auth
    # → installed_not_authed (không mark ready chỉ vì binary tồn tại).
    assume_authed: bool = False
    # Vendor API-key: env chứa key. binary=None → detect theo key, không theo which().
    api_key_env: list[str] | None = None
    # Vendor có catalog ĐỘNG (agy): lệnh liệt kê model. Chọn mở rộng schema thay vì
    # viết detector riêng — giữ MỘT đường detect() để fixture-hoá đồng nhất
    # (Grok red-team chê cả 2 phương án; đây là cái ít fork control-flow hơn).
    models_cmd: list[str] | None = None

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
        auth_check_authoritative=False,
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
    "agy": VendorSpec(
        name="agy",
        binary="agy",
        auth_hint="chạy `agy` để auth Antigravity",
        version_cmd=["agy", "--version"],
        # `agy models` vừa là auth-check vừa là nguồn catalog. Rủi ro đã biết
        # (Grok P0): lỗi mạng/API listing cũng làm returncode != 0 → báo
        # installed_not_authed dù credential còn sống. Chấp nhận có ý thức: thà
        # skip nhầm một lane (degrade) còn hơn báo ready rồi nổ lúc dispatch.
        auth_check_cmd=["agy", "models"],
        auth_check_authoritative=False,
        models_cmd=["agy", "models"],
    ),
    "openrouter": VendorSpec(
        name="openrouter",
        binary=None,  # hosted API, không có CLI
        auth_hint="lấy key free tại openrouter.ai/keys rồi `export OPENROUTER_API_KEY=...`",
        version_cmd=None,
        auth_check_cmd=None,
        api_key_env=["OPENROUTER_API_KEY", "OR_API_KEY"],
    ),
    "dsh": VendorSpec(
        name="dsh",
        binary="dsh",
        auth_hint="export DEEPSEEK_API_KEY (lấy từ Keychain: security find-generic-password -a $USER -s DEEPSEEK_API_KEY -w)",
        version_cmd=["dsh", "--version"],
        # --dump-config chạy 0 token, đủ để biết binary sống + credential
        auth_check_cmd=["dsh", "--profile", "headless", "--dump-config"],
        auth_check_authoritative=False,
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

# Slug model hợp lệ: chữ thường/số/`.`/`-`/`_`, không khoảng trắng, ≤64 ký tự.
# Lọc allowlist thay vì split thô (Grok P1): banner, mã màu ANSI, dòng
# "Available models:" hay warning trên stdout sẽ không lọt vào catalog.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,63}$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_AUTH_FAILURE_RE = re.compile(r"\b(?:not logged in|login required|unauthenticated|unauthorized)\b", re.I)


def parse_models(stdout: str) -> list[str]:
    """Lấy slug ở TOKEN ĐẦU mỗi dòng.

    Codex review: `agy models` có thể in dạng bảng `<slug>  <mô tả>` hoặc
    `* <slug> (default)` — bắt cả dòng thì mất sạch catalog và báo nhầm
    catalog_empty. Đổi lại phải chặt hơn: token phải chứa `-`, `.`, `_` hoặc `/`
    để chữ thường đơn lẻ ("models", "default") không lọt vào catalog.
    """
    out: list[str] = []
    for raw in (stdout or "").splitlines():
        line = _ANSI_RE.sub("", raw).strip().lstrip("*-• \t").strip()
        if not line:
            continue
        token = line.split()[0].rstrip(",;")
        if not _SLUG_RE.match(token) or not any(c in token for c in "-._/"):
            continue
        if token not in out:
            out.append(token)
    return out


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
    authed: bool | None = False
    error = None
    quota_capped = False
    models: list[str] = []

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
            # Codex review: auth-check rớt vì HẾT QUOTA không phải là "chưa auth".
            # Credential vẫn sống → authed=True + quota_capped để máy trạng thái
            # ra `quota_capped`, đúng lane failover thay vì bảo user đi login lại.
            if not authed and is_quota_error(res.stderr or "", res.returncode):
                authed, quota_capped = True, True
                error = error or f"quota (exit {res.returncode})"
            elif (not authed and not spec.auth_check_authoritative
                  and not _AUTH_FAILURE_RE.search(res.stderr or "")):
                authed = None
                error = f"auth_probe_unverified (exit {res.returncode})"
        else:
            # Không có cách kiểm auth: chỉ ready nếu policy assume_authed (host claude).
            authed = spec.assume_authed

        # Catalog động (agy): hỏi CLI, KHÔNG hardcode danh sách dự phòng — model
        # Antigravity đổi theo mùa, list cứng sẽ nói dối và làm watcher mù
        # (Grok P0). Catalog rỗng mà vẫn auth = ready + error='catalog_empty':
        # giữ tín hiệu sự cố thay vì im lặng khoe khoẻ.
        if authed and spec.models_cmd:
            same_cmd = spec.models_cmd == spec.auth_check_cmd
            if same_cmd:
                models = parse_models(res.stdout or "") or parse_models(res.stderr or "")
            else:
                mres = runner([abs_path] + spec.models_cmd[1:],
                              capture_output=True, text=True, timeout=10)
                models = (parse_models(mres.stdout or "") or parse_models(mres.stderr or "")
                          ) if mres.returncode == 0 else []
            if not models:
                error = error or "catalog_empty"
    except subprocess.TimeoutExpired:
        if spec.auth_check_authoritative:
            error, authed = "timeout", False
        else:
            error, authed = "auth_probe_unverified (timeout)", None
    except (OSError, subprocess.SubprocessError) as e:
        # Path chết sau which(), symlink hỏng, permission... → mã lỗi ổn định.
        error = f"{type(e).__name__}: {e}"
        authed = False

    return VendorProbe(
        name=spec.name,
        path=abs_path,
        authed=authed,
        quota_capped=quota_capped,
        version=version,
        models=models,
        error=error
    )

def detect_all(specs=None, which=shutil.which, runner=subprocess.run) -> list[VendorProbe]:
    if specs is None:
        specs = list(REGISTRY.values())
    return [detect(spec, which=which, runner=runner) for spec in specs]
