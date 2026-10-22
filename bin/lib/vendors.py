from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
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
    # BUG-15 (23/08): timeout riêng cho probe auth. Probe CỤC BỘ giữ 10s để hỏng
    # thật còn báo nhanh; probe GỌI MẠNG (agy models) phải nới ra — nó là phép đo
    # chịu ảnh hưởng của tải máy, không phải hằng số. Đo thật trên M1 8GB:
    # load ~4 → 2,2-3,1s · load ~84 → tới 8,2s · load ~93 → vượt 10s.
    auth_check_timeout: int = 10
    # Khi không có auth_check_cmd: True = coi như đã auth (host claude);
    # None = không có verified auth cmd (auth_unverified);
    # False = chưa rõ auth → installed_not_authed.
    assume_authed: bool | None = False
    # Vendor API-key: env chứa key. binary=None → detect theo key, không theo which().
    api_key_env: list[str] | None = None
    # Vendor có catalog ĐỘNG (agy, codex, opencode): lệnh liệt kê model.
    models_cmd: list[str] | None = None
    provider: str | None = None
    quota_group: str | None = None

REGISTRY: dict[str, VendorSpec] = {
    "codex": VendorSpec(
        name="codex",
        binary="codex",
        auth_hint="chạy `codex login`",
        version_cmd=["codex", "--version"],
        auth_check_cmd=["codex", "login", "status"],
        models_cmd=["codex", "debug", "models"],
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
        auth_check_timeout=30,
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
    "opencode": VendorSpec(
        name="opencode",
        binary=str(Path.home() / ".opencode" / "bin" / "opencode"),
        auth_hint="kiểm tra credentials Go tại ~/.opencode",
        version_cmd=["opencode", "--version"],
        auth_check_cmd=None,
        auth_check_authoritative=False,
        assume_authed=None,
        models_cmd=["opencode", "models", "opencode-go"],
        provider="opencode-go",
        quota_group="opencode-go",
    ),
    "hermes": VendorSpec(
        name="hermes",
        binary="hermes",
        auth_hint="kiểm tra ~/.hermes hoặc hermes config",
        version_cmd=["hermes", "--version"],
        auth_check_cmd=None,
        auth_check_authoritative=False,
        assume_authed=None,
        models_cmd=None,
        provider="opencode-go",
        quota_group="opencode-go",
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


def parse_codex_models(stdout: str) -> list[str]:
    """Parse catalog JSON từ `codex debug models`.

    Dùng json, KHÔNG dùng parse_models token thô.
    Shape biết được: {"models": [{"slug": "<model-slug>", ...}, ...]}.
    Chưa biết shape thì fail explicit (ValueError/KeyError), không tự bịa / invent.
    """
    if not stdout or not stdout.strip():
        raise ValueError("codex models output is empty")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise ValueError(f"codex models output is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(f"codex models expected JSON object, got {type(data).__name__}")

    if "models" not in data:
        raise KeyError("codex models JSON missing 'models' key")

    models_list = data["models"]
    if not isinstance(models_list, list):
        raise ValueError(f"codex models 'models' field must be a list, got {type(models_list).__name__}")

    slugs: list[str] = []
    for idx, item in enumerate(models_list):
        if not isinstance(item, dict):
            raise ValueError(f"codex models item #{idx} must be a dict, got {type(item).__name__}")
        if "slug" not in item:
            raise KeyError(f"codex models item #{idx} missing required key 'slug'")
        slug = item["slug"]
        if not isinstance(slug, str) or not slug.strip():
            raise ValueError(f"codex models item #{idx} has invalid slug: {slug!r}")
        clean_slug = slug.strip()
        if clean_slug not in slugs:
            slugs.append(clean_slug)
    return slugs


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


class _ProbeTimeout(Exception):
    """Probe auth hết giờ SAU KHI đã thử lại — mang theo bằng chứng để báo cáo.

    Tách riêng khỏi subprocess.TimeoutExpired vì handler chung của detect() còn
    bắt timeout của version_cmd/models_cmd; gộp chung thì thông điệp nói sai chỗ.
    """
    def __init__(self, elapsed: float, attempts: int, limit: int):
        self.elapsed, self.attempts, self.limit = elapsed, attempts, limit
        super().__init__(f"auth probe timeout sau {elapsed:.1f}s")


def _run_auth_check(spec: VendorSpec, abs_path: str, runner):
    """Chạy auth_check_cmd với timeout RIÊNG theo spec, thử lại 1 lần nếu hết giờ.

    BUG-15: timeout cứng 10s cho lệnh gọi mạng biến tải máy thành lỗi ngẫu nhiên.
    Thử lại chỉ áp cho probe KHÔNG authoritative — vendor nào tự nhận "probe của
    tôi phân biệt được chưa-auth với lỗi khác" thì hết giờ là kết luận được luôn,
    không cần tốn thêm một lượt chờ.
    """
    cmd = [abs_path] + spec.auth_check_cmd[1:]
    limit = spec.auth_check_timeout
    max_attempts = 2 if not spec.auth_check_authoritative else 1
    tong = 0.0
    for lan in range(1, max_attempts + 1):
        t0 = time.monotonic()
        try:
            return runner(cmd, capture_output=True, text=True, timeout=limit)
        except subprocess.TimeoutExpired:
            tong += time.monotonic() - t0
            if lan == max_attempts:
                raise _ProbeTimeout(tong, lan, limit) from None


# BUG-14: lane Go (opencode/hermes) là lane DUY NHẤT auth phải suy từ bằng chứng
# dispatch — probe CLI ở lane này chỉ liệt kê catalog, không phải auth status.
GO_QUOTA_GROUP = "opencode-go"


def _is_go_lane(spec: VendorSpec) -> bool:
    """Vendor thuộc lane Go (quota group dùng chung opencode-go)?"""
    return spec.quota_group == GO_QUOTA_GROUP


def _read_evidence_safe(limit: int = 200) -> list[dict]:
    """Đọc evidence log, lỗi/thiếu file → [] (không được làm nổ detect)."""
    try:
        from lib.evidence import read_evidence
        recs = read_evidence(limit=limit)
    except Exception:
        return []
    return recs if isinstance(recs, list) else []


def detect(
    spec: VendorSpec,
    which=shutil.which,
    runner=subprocess.run,
    records: list[dict] | None = None,
    now: str | datetime | None = None,
) -> VendorProbe:
    if spec.binary is None:
        return _detect_api_key_vendor(spec)
    path_str = which(spec.binary)
    if path_str is None and spec.binary and "/" in spec.binary:
        # Hỗ trợ mock which chỉ so khớp basename thay vì đường dẫn tuyệt đối
        path_str = which(Path(spec.binary).name)
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
            res = _run_auth_check(spec, abs_path, runner)
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
                # BUG-13 (20/08): trước đây chỉ ghi mã thoát, VỨT stderr. Người
                # đọc thấy nhãn `auth_unverified` sẽ đi kiểm auth — trong khi
                # nguyên nhân thật có thể là cờ sai, mạng, hay CLI đổi cú pháp.
                # Nhãn nói SAI CHỖ, mà bằng chứng để cãi lại thì đã bị vứt.
                chi_tiet = " | ".join((res.stderr or "").strip().splitlines()[-3:])[:300]
                error = f"auth_probe_unverified (exit {res.returncode})"
                if chi_tiet:
                    error += f" — stderr: {chi_tiet}"
        else:
            # Không có cách kiểm auth (auth_check_cmd=None):
            # assume_authed=True -> authed=True (host claude)
            # assume_authed=None -> authed=None (auth_unverified: không có verified auth cmd, không dump credential, không inference)
            # assume_authed=False -> authed=False (installed_not_authed)
            authed = spec.assume_authed

        # BUG-14: suy auth/quota từ live dispatch evidence — CHỈ lane Go và CHỈ khi có
        # mốc thời gian để so TTL. Vendor khác giữ nguyên kết luận của probe mình
        # (assume_authed / auth_check_cmd): bằng chứng lane Go không được đổi trạng thái
        # claude/codex/agy/gemini, và evidence không có `ts` thì không phải bằng chứng.
        # Regression BUG-14 lô 5a: dispatcher gọi detect(spec) KHÔNG truyền `now`; nhánh
        # quota cap cũ gọi now.isoformat() trên None → AttributeError, CLI mất luôn JSON.
        if _is_go_lane(spec):
            from lib.doctor_quota import (
                evaluate_auth_evidence,
                normalize_now_iso,
                quota_capped_since,
            )
            if records is None:
                records = _read_evidence_safe()
            now_iso = normalize_now_iso(now)
            if now_iso and records:
                if authed is None:
                    auth_res = evaluate_auth_evidence(
                        records,
                        spec.name,
                        now_iso,
                        provider=spec.provider,
                        quota_group=spec.quota_group,
                    )
                    if auth_res["authed"] is True:
                        authed = True
                        error = None
                    elif auth_res["authed"] is False:
                        authed = False
                        error = auth_res.get("reason") or "explicit_auth_failure"

                # Quota cap newest wins — chỉ hạ vendor vừa được xác minh là authed.
                if authed is True and not quota_capped:
                    capped_map = quota_capped_since(records, now_iso)
                    if spec.name in capped_map:
                        quota_capped = True

        # Catalog động: hỏi CLI, KHÔNG hardcode danh sách dự phòng.
        # Với vendor authed=True hoặc authed=None (như opencode: không suy ready từ catalog,
        # nhưng vẫn lấy danh mục model nếu lệnh models_cmd có sẵn).
        if (authed is True or authed is None) and spec.models_cmd:
            same_cmd = spec.models_cmd == spec.auth_check_cmd
            if same_cmd:
                models = parse_models(res.stdout or "") or parse_models(res.stderr or "")
            else:
                mres = runner([abs_path] + spec.models_cmd[1:],
                              capture_output=True, text=True, timeout=10)
                if mres.returncode == 0:
                    if spec.name == "codex":
                        try:
                            models = parse_codex_models(mres.stdout or "")
                        except Exception as e:
                            models = []
                            error = error or f"catalog_parse_error: {e}"
                    else:
                        models = (parse_models(mres.stdout or "") or parse_models(mres.stderr or ""))
                else:
                    models = []
                    chi_tiet = " | ".join((mres.stderr or "").strip().splitlines()[-3:])[:300]
                    if chi_tiet:
                        error = error or f"models_cmd_failed (exit {mres.returncode}) — stderr: {chi_tiet}"
            if not models and not error:
                error = "catalog_empty"
    except _ProbeTimeout as e:
        # BUG-15: nói RÕ hết giờ bao lâu, ngưỡng bao nhiêu, thử mấy lần — đọc là
        # biết ngay do timeout chứ không phải credential chết. Timeout không có
        # mã thoát nào cả, phải ghi thẳng ra thay vì để người đọc tự đoán.
        chi_tiet = (f"timeout sau {e.elapsed:.1f}s (ngưỡng {e.limit}s/lượt, "
                    f"{e.attempts} lượt, không có mã thoát)")
        if spec.auth_check_authoritative:
            error, authed = f"auth_probe_timeout — {chi_tiet}", False
        else:
            error, authed = f"auth_probe_unverified — {chi_tiet}", None
    except subprocess.TimeoutExpired:
        # Timeout của version_cmd hoặc models_cmd — KHÔNG phải probe auth.
        if spec.assume_authed is None:
            error, authed = "auth_probe_unverified (timeout)", None
        elif spec.auth_check_authoritative:
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

def detect_all(
    specs=None,
    which=shutil.which,
    runner=subprocess.run,
    records: list[dict] | None = None,
    now: str | datetime | None = None,
) -> list[VendorProbe]:
    if specs is None:
        specs = list(REGISTRY.values())
    # Chỉ đọc evidence khi có ít nhất một vendor lane Go — vendor khác không dùng
    # bằng chứng dispatch, đọc log ở đây chỉ tốn I/O và dễ gây nhiễu test.
    if records is None and any(_is_go_lane(spec) for spec in specs):
        records = _read_evidence_safe()
    if now is None:
        now = datetime.now(timezone.utc).isoformat()
    return [detect(spec, which=which, runner=runner, records=records, now=now) for spec in specs]
