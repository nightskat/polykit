"""Vision security gate, format verification, and PDF conversion for PolyKit.

Pure API for vision gatekeeping before ANY file I/O, subprocess, or network call.
Quy tắc chính sách (P3, Plan 2026-10-22 mục Lane VISION, Grok Findings 1+2):
1. Cổng PII / sensitive:
   - Dữ liệu thật / sensitive hoặc không tuyên bố synthetic rõ phải blocked mặc định.
   - Cờ --allow-sensitive-vision là không đủ.
   - Bắt buộc confirmation một lượt gắn exact (files, model, provider), không lưu hoặc
     kế thừa qua retry/failover.
   - Vì chưa có UI xác nhận Tuan đáng tin, sensitive luôn bị blocked fail-closed;
     KHÔNG nhận bất kỳ chuỗi string nào làm consent.
   - Gate sensitive kiểm tra TRƯỚC mọi file I/O, probe, stat, open hay subprocess.
2. Synthetic explicit:
   - File phải là regular file, cấm symlink, cấm path outside allowed workspace.
   - MIME signature kiểm tra qua magic bytes (không chỉ dựa vào suffix):
     * image/png: b'\\x89PNG\\r\\n\\x1a\\n'
     * image/jpeg: b'\\xff\\xd8\\xff'
     * application/pdf: b'%PDF'
   - Hạn dung lượng tối đa (file size limit).
   - Xử lý đúng path có khoảng trắng.
3. Capabilities metadata & adapter verification:
   - Trusted model capabilities:
     * deepseek-v4.1-flash: image=true, pdf=false
     * glm-5.3-flash: image=true, pdf=true
     * mimo-v2.6-flash: image=true, pdf=false
     * deepseek-v4-pro: image=false, pdf=false
     * glm-5.3: image=false, pdf=false
     * *-contributor: blocked hoàn toàn
   - Adapter verification:
     * API public KHÔNG được tự chứng nhận adapter (không nhận verified_adapters param).
     * Adapter rỗng ("" / None / whitespace) bị blocked fail-closed trước bất kỳ I/O.
     * Chỉ so khớp với hằng frozen registry VERIFIED_VISION_ADAPTERS (hiện rỗng).
     * Không caller flag/token tự tạo mở chốt.
4. DeepSeek PDF conversion:
   - Hàm public convert_pdf_to_images bị blocked fail-closed trước bất kỳ I/O,
     không nhận pdftoppm_bin arbitrary để bypass.
   - Việc tách PDF chỉ đi qua prepare_vision_input sau khi vượt gate an toàn,
     thực hiện qua helper nội bộ _convert_pdf_to_images.
   - Dùng pdftoppm tách trang full res, subprocess argv, timeout rõ ràng.
   - Tách theo numeric order tự nhiên (1, 2, ..., 10), không dùng contact sheet.
   - Thiếu binary pdftoppm phải blocked.
   - Không mở PDF thật trước gate.
   - MỖI conversion ghi vào thư mục private MỚI (``tempfile.mkdtemp`` prefix
     ``polykit-vision-`` trong TMPDIR), không bao giờ ghi/đọc thư mục của caller.
   - Caller ``output_dir`` bị reject fail-closed: thư mục caller có thể chứa file
     cũ/symlink cùng prefix, nên không được dùng làm đầu ra.
   - Không glob file cũ: chỉ nhận entry khớp chính xác ``<prefix>-<số>.png``,
     là regular file thật (không symlink), page id liên tục 1..N, số trang và
     dung lượng bị chặn trần.
5. Privacy:
   - Tuyệt đối không log nội dung file hay PII trong log/error.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class VisionError(Exception):
    """Base exception for all vision module errors."""
    pass


class VisionBlockedError(VisionError):
    """Raised when vision request is blocked by safety gate, policy, or unverified status."""
    pass


class VisionSecurityError(VisionBlockedError):
    """Raised on security violations: symlink, path traversal, or workspace escape."""
    pass


class VisionFormatError(VisionBlockedError):
    """Raised on invalid format, MIME signature mismatch, missing file, or empty file."""
    pass


class VisionQuotaError(VisionBlockedError):
    """Raised when file size exceeds limits."""
    pass


class VisionConversionError(VisionBlockedError):
    """Raised when PDF conversion via pdftoppm fails or times out."""
    pass


# ---------------------------------------------------------------------------
# Constants & Trusted Metadata
# ---------------------------------------------------------------------------

DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB

# Trusted capabilities metadata per model
TRUSTED_MODEL_CAPABILITIES: dict[str, dict[str, bool]] = {
    "deepseek-v4.1-flash": {"image": True, "pdf": False},
    "glm-5.3-flash": {"image": True, "pdf": True},
    "mimo-v2.6-flash": {"image": True, "pdf": False},
    "deepseek-v4-pro": {"image": False, "pdf": False},
    "glm-5.3": {"image": False, "pdf": False},
}

# Adapters verified for vision attachments.
# opencode được xác minh cho vision synthetic generator-backed (Lô 2). hermes giữ block.
VERIFIED_VISION_ADAPTERS: frozenset[str] = frozenset({"opencode"})

# Pinned trusted hashes registry artifact from repo generator (Lô 1).
# Ngăn caller tự viết manifest để bypass generator.
TRUSTED_SYNTHETIC_REGISTRY: dict[str, dict[str, Any]] = {
    "page_01_narrow_table.png": {
        "sha256": "8fff419916fed503b1053309281539c51ea4ab5043de19c600877d1c513001c2",
        "bytes": 83477,
        "format": "PNG",
        "rel_path": "bench/vision/synthetic/page_01_narrow_table.png",
    },
    "page_02_negative_numbers.png": {
        "sha256": "97592980dcd3236e573cd6d2326987d23ba57c96f810e8bae17bb77c21c6a462",
        "bytes": 69862,
        "format": "PNG",
        "rel_path": "bench/vision/synthetic/page_02_negative_numbers.png",
    },
    "page_03_confusing_chars.png": {
        "sha256": "027cc6ad2bbda8dd69b4c9a87948993021c9553034e665cd42cbc371df8373dd",
        "bytes": 76182,
        "format": "PNG",
        "rel_path": "bench/vision/synthetic/page_03_confusing_chars.png",
    },
    "page_04_degraded_scan.png": {
        "sha256": "859eb2fc864f24be1290fc8b3b6db5f38f7e6ba39945da829e62f2372dfbdaa0",
        "bytes": 346749,
        "format": "PNG",
        "rel_path": "bench/vision/synthetic/page_04_degraded_scan.png",
    },
    "page_05_multipage_p1.png": {
        "sha256": "bf5a6a796fb11dcf8a83ba0d1e641bbb03cc459dd49a5547c9d468539e0f0971",
        "bytes": 82318,
        "format": "PNG",
        "rel_path": "bench/vision/synthetic/page_05_multipage_p1.png",
    },
    "page_06_multipage_p2.png": {
        "sha256": "fc1f2612983f7a744868fbf697e651cb816e3a4041aa90d4348cdd966908a358",
        "bytes": 60473,
        "format": "PNG",
        "rel_path": "bench/vision/synthetic/page_06_multipage_p2.png",
    },
    "multipage_contract.pdf": {
        "sha256": "e5769a2dc65b5d38f708b3e0df9e3b8c6f17635fcd543a6b35773af380344cc1",
        "bytes": 191453,
        "format": "PDF",
        "rel_path": "bench/vision/synthetic/multipage_contract.pdf",
    },
}

EXPECTED_MANIFEST_SCHEMA_VERSION = 1
EXPECTED_MANIFEST_GENERATOR = "bench/vision/generate.py"

# Định dạng khai báo trong manifest/registry → MIME thực tế phải khớp magic bytes.
_FORMAT_TO_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "PDF": "application/pdf",
}
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

# Repo root định danh cố định từ vị trí file này — KHÔNG đọc --cd/workdir/cwd.
# Cố ý là module CONSTANT (không có setter, không có override public): test muốn
# cô lập fixture thì monkeypatch thẳng constant này, nhưng sản phẩm không có
# đường nào để caller đổi repo gốc ⇒ không thể trỏ cổng sang "repo giả".
REAL_REPO_ROOT = Path(__file__).resolve().parents[2]

# MIME Magic Signatures
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
PDF_MAGIC = b"%PDF"

SUPPORTED_MIME_TYPES = {
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "application/pdf": {".pdf"},
}

# ---- PDF conversion bounds (fail-closed) ----------------------------------
# Mỗi conversion chỉ nhận tối đa chừng này trang, mỗi trang và tổng output bị
# chặn trần để một PDF độc/hỏng không làm ngập TMPDIR hay RAM của bước dispatch.
MAX_CONVERSION_PAGES = 64
MAX_CONVERSION_PAGE_BYTES = DEFAULT_MAX_FILE_BYTES
MAX_CONVERSION_TOTAL_BYTES = 512 * 1024 * 1024

# Prefix đầu ra page: chỉ [A-Za-z0-9_-], tối đa 64 ký tự. Prefix do caller/stem
# PDF quyết nên phải sanitize trước khi ghép tên file.
_PREFIX_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_PREFIX_LEN = 64


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SingleTurnConfirmation:
    """Single-turn confirmation binding exact files, model, and provider.

    Cannot be reused across retries or failover.
    """
    token: str
    exact_files: tuple[str, ...]
    exact_model: str
    exact_provider: str
    is_trusted_ui: bool = False
    consumed: bool = False

    def is_valid_for(
        self,
        files: Sequence[str | Path],
        model: str,
        provider: str,
        is_retry: bool = False,
        is_failover: bool = False,
    ) -> tuple[bool, str]:
        if is_retry or is_failover:
            return False, "Confirmation cannot be inherited across retry or failover"
        if self.consumed:
            return False, "Confirmation has already been consumed"
        if not self.is_trusted_ui:
            return False, "trusted UI confirmation is not supported yet"

        norm_files = tuple(str(Path(f)) for f in files)
        if norm_files != self.exact_files:
            return False, "Confirmation files do not match exact request files"
        if model != self.exact_model:
            return False, "Confirmation model does not match exact request model"
        if provider != self.exact_provider:
            return False, "Confirmation provider does not match exact request provider"
        return True, ""


@dataclass(frozen=True)
class VisionAttachment:
    """Validated attachment metadata."""
    path: Path
    mime_type: str
    size_bytes: int
    is_synthetic: bool = True

    @property
    def is_pdf(self) -> bool:
        return self.mime_type == "application/pdf"

    @property
    def is_image(self) -> bool:
        return self.mime_type in ("image/png", "image/jpeg")


# ---------------------------------------------------------------------------
# MIME Signature & File Helpers
# ---------------------------------------------------------------------------

def detect_mime_from_magic_bytes(header: bytes) -> str | None:
    """Inspect magic bytes to determine actual MIME type."""
    if header.startswith(PNG_MAGIC):
        return "image/png"
    if header.startswith(JPEG_MAGIC):
        return "image/jpeg"
    if header.startswith(PDF_MAGIC):
        return "application/pdf"
    return None


def validate_file_format(
    path: Path,
    workspace_root: Path,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> VisionAttachment:
    """Validate path safety, existence, size, and MIME signature.

    No PII or file content is logged or printed.
    """
    # 1. Symlink check (cấm symlink)
    if path.is_symlink() or os.path.islink(path):
        raise VisionSecurityError(f"Symlinks are blocked for vision: {path.name}")

    # 2. Workspace boundary check (cấm path outside workspace)
    try:
        resolved = path.resolve(strict=False)
        resolved_ws = workspace_root.resolve(strict=True)
        resolved.relative_to(resolved_ws)
    except (ValueError, RuntimeError):
        raise VisionSecurityError(f"File path outside allowed workspace: {path.name}")

    # 3. Existence and regular file check
    if not resolved.exists():
        raise VisionFormatError(f"File not found: {path.name}")
    if not resolved.is_file():
        raise VisionFormatError(f"Not a regular file: {path.name}")

    # 4. File size limits
    size = resolved.stat().st_size
    if size == 0:
        raise VisionFormatError(f"File is empty: {path.name}")
    if size > max_bytes:
        raise VisionQuotaError(
            f"File size ({size} bytes) exceeds maximum limit ({max_bytes} bytes)"
        )

    # 5. Extension check
    suffix = resolved.suffix.lower()
    valid_suffix = any(suffix in exts for exts in SUPPORTED_MIME_TYPES.values())
    if not valid_suffix:
        raise VisionFormatError(f"Unsupported file extension: {suffix}")

    # 6. MIME signature via magic bytes
    try:
        with resolved.open("rb") as f:
            header = f.read(32)
    except OSError as e:
        raise VisionFormatError(f"Failed to read file header: {path.name}") from e

    detected_mime = detect_mime_from_magic_bytes(header)
    if detected_mime is None:
        raise VisionFormatError(
            f"File header magic bytes do not match any supported format for {path.name}"
        )

    expected_exts = SUPPORTED_MIME_TYPES.get(detected_mime, set())
    if suffix not in expected_exts:
        raise VisionFormatError(
            f"MIME signature '{detected_mime}' does not match file suffix '{suffix}'"
        )

    return VisionAttachment(
        path=resolved,
        mime_type=detected_mime,
        size_bytes=size,
        is_synthetic=True,
    )


# ---------------------------------------------------------------------------
# Capabilities & Adapter Checks
# ---------------------------------------------------------------------------

def get_model_capabilities(model: str) -> dict[str, bool]:
    """Retrieve trusted capabilities for model.

    Raises VisionBlockedError if model is contributor or unknown.
    """
    if not model or not isinstance(model, str):
        raise VisionBlockedError("Model identifier must be a non-empty string")

    # Contributor models always blocked
    if model.lower().endswith("-contributor"):
        raise VisionBlockedError(f"Contributor model '{model}' is blocked for vision")

    caps = TRUSTED_MODEL_CAPABILITIES.get(model.lower())
    if caps is None:
        raise VisionBlockedError(
            f"Model '{model}' vision capabilities are unverified; blocked"
        )
    return caps


def verify_adapter(adapter: str) -> None:
    """Ensure adapter has verified vision attachment support.

    Blank adapter is blocked fail-closed.
    Only adapters in frozen VERIFIED_VISION_ADAPTERS registry are permitted.
    Caller cannot supply custom verified adapters to bypass this gate.
    """
    if not adapter or not isinstance(adapter, str) or not adapter.strip():
        raise VisionBlockedError(
            "Vision adapter must be specified and non-empty; blank adapter is blocked"
        )
    if adapter not in VERIFIED_VISION_ADAPTERS:
        raise VisionBlockedError(
            f"Vision adapter '{adapter}' is not verified; blocked"
        )


# ---------------------------------------------------------------------------
# Core Vision Gate & Synthetic Validation
# ---------------------------------------------------------------------------

def check_no_symlinks(path: Path, root: Path) -> None:
    """Ensure neither path nor any ancestor up to and including root is a symlink."""
    # Check root itself
    if os.path.islink(root) or root.is_symlink():
        raise VisionSecurityError(f"Symlink detected in root ancestor: {root}")

    # Check path and all ancestors up to root without dereferencing
    curr = path
    while True:
        if os.path.islink(curr) or curr.is_symlink():
            raise VisionSecurityError(f"Symlink detected in path or ancestor: {curr}")
        if curr == root or curr == curr.parent:
            break
        curr = curr.parent


def validate_synthetic_gate(
    files: Sequence[str | Path],
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> list[VisionAttachment]:
    """Strict security and authenticity gate for synthetic vision attachments:
    - Fixed bench/vision/synthetic/ under REAL_REPO_ROOT (immune to fake --cd/cwd).
    - Manifest schema_version=1, generator=bench/vision/generate.py.
    - Manifest entries match pinned trusted hashes registry.
    - Manifest and all ancestor directories must NOT be symlinks.
    - Attachment files must reside inside bench/vision/synthetic/.
    - Attachment files and all their ancestor directories must NOT be symlinks.
    - No path traversal, no outside repo, no malformed, duplicate, or missing files.
    - Requested filename MUST appear in the manifest (manifest là danh sách đóng:
      file có trong registry nhưng không được generator khai báo vẫn bị chặn).
    - Exact SHA-256 match against manifest, trusted registry, and file on disk.
    - Magic bytes and file size match expected.

    Không có tham số ``repo_root``: cổng luôn đọc constant module
    ``REAL_REPO_ROOT`` (monkeypatch được trong test, sản phẩm thì không).
    """
    if not files:
        raise VisionFormatError("No attachment files provided for vision")

    root = REAL_REPO_ROOT
    trusted_reg = TRUSTED_SYNTHETIC_REGISTRY
    synth_dir = root / "bench" / "vision" / "synthetic"
    manifest_path = synth_dir / "manifest.json"

    # 1. Symlink checks on directory hierarchy and manifest
    check_no_symlinks(synth_dir, root)
    check_no_symlinks(manifest_path, root)

    # 2. Check manifest existence & regular file
    if not manifest_path.exists() or not manifest_path.is_file():
        raise VisionBlockedError(f"Synthetic manifest not found: {manifest_path}")

    # 3. Parse manifest
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        raise VisionBlockedError(f"Malformed synthetic manifest JSON: {e}") from e

    if not isinstance(manifest, dict):
        raise VisionBlockedError("Manifest root must be a JSON object")

    # ``type(...) is int`` (không dùng ==) để loại schema_version=true (bool),
    # vì True == 1 trong Python và sẽ lọt cổng nếu chỉ so sánh giá trị.
    schema_version = manifest.get("schema_version")
    if type(schema_version) is not int or schema_version != EXPECTED_MANIFEST_SCHEMA_VERSION:
        raise VisionBlockedError(
            f"Invalid manifest schema_version: {manifest.get('schema_version')!r}"
        )

    if manifest.get("generator") != EXPECTED_MANIFEST_GENERATOR:
        raise VisionBlockedError(
            f"Invalid manifest generator: {manifest.get('generator')!r}"
        )

    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, list) or not manifest_files:
        raise VisionBlockedError("Manifest files must be a non-empty list")

    # 4. Verify manifest against trusted generator registry (pinned artifact)
    seen_manifest_files: set[str] = set()
    manifest_map: dict[str, dict[str, Any]] = {}

    for entry in manifest_files:
        if not isinstance(entry, dict):
            raise VisionBlockedError("Manifest file entry must be a dictionary")

        fname = entry.get("path")
        if not isinstance(fname, str) or not fname:
            raise VisionBlockedError("Manifest file missing path string")
        # Manifest là danh sách đóng trong MỘT thư mục: chỉ nhận tên file trần,
        # không separator, không '.', không '..', không đường dẫn tuyệt đối.
        if fname in (".", "..") or "/" in fname or "\\" in fname or Path(fname).name != fname:
            raise VisionBlockedError(
                f"Manifest file path must be a plain filename: {fname!r}"
            )
        if fname in seen_manifest_files:
            raise VisionBlockedError(f"Duplicate file in manifest: {fname}")
        seen_manifest_files.add(fname)

        if fname not in trusted_reg:
            raise VisionBlockedError(
                f"Manifest file {fname} is not in trusted generator registry"
            )

        record = trusted_reg[fname]
        if not isinstance(record, dict):
            raise VisionBlockedError(f"Trusted registry entry for {fname} is malformed")

        sha = entry.get("sha256")
        if not isinstance(sha, str) or not _SHA256_HEX_RE.match(sha.lower()):
            raise VisionBlockedError(f"Manifest file {fname} missing/invalid sha256")

        expected_sha = str(record.get("sha256", "")).lower()
        if not _SHA256_HEX_RE.match(expected_sha):
            raise VisionBlockedError(f"Trusted registry sha256 for {fname} is malformed")
        if sha.lower() != expected_sha:
            raise VisionBlockedError(
                f"Manifest sha256 mismatch for {fname} against trusted generator registry"
            )

        # bytes phải là int thật (bool bị loại vì True == 1) và khớp registry.
        expected_bytes = record.get("bytes")
        if type(expected_bytes) is not int or expected_bytes <= 0:
            raise VisionBlockedError(f"Trusted registry bytes for {fname} is malformed")
        entry_bytes = entry.get("bytes")
        if type(entry_bytes) is not int or entry_bytes != expected_bytes:
            raise VisionBlockedError(
                f"Manifest byte size mismatch for {fname} against trusted generator registry"
            )

        # format (nếu khai) phải khớp registry; rel_path (nếu khai) phải đúng cây.
        declared_format = entry.get("format")
        expected_format = record.get("format")
        if declared_format is not None:
            if (
                not isinstance(declared_format, str)
                or not isinstance(expected_format, str)
                or declared_format.upper() != expected_format.upper()
            ):
                raise VisionBlockedError(f"Manifest format mismatch for {fname}")

        declared_rel = entry.get("rel_path")
        expected_rel = record.get("rel_path")
        if declared_rel is not None and declared_rel != expected_rel:
            raise VisionBlockedError(f"Manifest rel_path mismatch for {fname}")

        manifest_map[fname] = entry

    # 5. Validate caller attachments
    validated: list[VisionAttachment] = []
    seen_attachments: set[str] = set()

    for item in files:
        if not item:
            raise VisionFormatError("Empty file path provided")
        p = Path(item)

        # Path traversal check
        if ".." in p.parts:
            raise VisionSecurityError(f"Path traversal detected in attachment: {item}")

        # Resolve target path relative to synth_dir
        if p.is_absolute():
            target_path = p
        elif len(p.parts) == 1:
            target_path = synth_dir / p.name
        else:
            # e.g. bench/vision/synthetic/page_01.png
            target_path = root / p

        # Check outside synthetic dir
        try:
            rel = target_path.resolve(strict=False).relative_to(synth_dir.resolve(strict=False))
            if len(rel.parts) != 1:
                raise VisionSecurityError(
                    f"Attachment {item} must be directly inside {synth_dir}"
                )
        except (ValueError, RuntimeError):
            raise VisionSecurityError(
                f"Attachment {item} is outside fixed synthetic directory: {synth_dir}"
            )

        filename = target_path.name
        if filename in seen_attachments:
            raise VisionBlockedError(f"Duplicate attachment provided: {filename}")
        seen_attachments.add(filename)

        # Check symlink on file and all ancestors up to root
        check_no_symlinks(target_path, root)

        # Check file exists and is regular file
        if not target_path.exists():
            raise VisionFormatError(f"Synthetic file not found: {target_path}")
        if not target_path.is_file():
            raise VisionFormatError(f"Not a regular file: {target_path}")

        # Kiểm tra kích thước trước khi tra registry: file rỗng/quá trần trong
        # synthetic dir luôn bị chặn, không cần khai báo trong manifest.
        actual_size = target_path.stat().st_size
        if actual_size == 0:
            raise VisionFormatError(f"Synthetic file is empty: {filename}")
        if actual_size > max_bytes:
            raise VisionQuotaError(
                f"Synthetic file {filename} exceeds max size {max_bytes} bytes"
            )

        if filename not in trusted_reg:
            raise VisionBlockedError(
                f"File {filename} is not in trusted synthetic generator registry"
            )

        # Manifest là danh sách ĐÓNG: file có trong registry nhưng generator
        # không khai báo trong manifest thì không được coi là synthetic hợp lệ.
        if filename not in manifest_map:
            raise VisionBlockedError(
                f"Requested file {filename} is not declared in the synthetic manifest"
            )
        manifest_sha = str(manifest_map[filename].get("sha256", "")).lower()
        if manifest_sha != trusted_reg[filename]["sha256"].lower():
            raise VisionBlockedError(
                f"Manifest sha256 mismatch for {filename} against trusted generator registry"
            )

        actual_size = target_path.stat().st_size
        if actual_size == 0:
            raise VisionFormatError(f"Synthetic file is empty: {filename}")
        if actual_size > max_bytes:
            raise VisionQuotaError(
                f"Synthetic file {filename} exceeds max size {max_bytes} bytes"
            )

        expected_size = trusted_reg[filename].get("bytes")
        if expected_size is not None and actual_size != expected_size:
            raise VisionBlockedError(
                f"File size mismatch for {filename}: expected {expected_size}, got {actual_size}"
            )

        # SHA-256 calculation
        h = hashlib.sha256()
        with open(target_path, "rb") as fh:
            while chunk := fh.read(65536):
                h.update(chunk)
        actual_sha = h.hexdigest().lower()
        expected_sha = trusted_reg[filename]["sha256"].lower()

        if actual_sha != expected_sha:
            raise VisionBlockedError(
                f"File content modified/tampered for {filename}: sha256 mismatch"
            )

        # MIME signature via magic bytes
        with open(target_path, "rb") as fh:
            header = fh.read(32)
        mime = detect_mime_from_magic_bytes(header)
        if not mime:
            raise VisionFormatError(f"Invalid magic bytes signature for {filename}")

        # Định dạng registry phải khớp MIME thật (không tin suffix/manifest).
        registry_format = str(trusted_reg[filename].get("format", "")).upper()
        expected_mime = _FORMAT_TO_MIME.get(registry_format)
        if expected_mime is None or expected_mime != mime:
            raise VisionFormatError(
                f"Magic bytes for {filename} do not match trusted registry format"
            )

        validated.append(VisionAttachment(
            path=target_path,
            mime_type=mime,
            size_bytes=actual_size,
            is_synthetic=True,
        ))

    return validated


def check_vision_gate(
    files: Sequence[str | Path],
    model: str,
    provider: str = "",
    adapter: str = "",
    is_synthetic: bool = False,
    allow_sensitive: bool = False,
    confirmation: Any = None,
    is_retry: bool = False,
    is_failover: bool = False,
    workspace_root: str | Path | None = None,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> list[VisionAttachment]:
    """Pure gate check before ANY file I/O, subprocess, or network call.

    GATE CHECK ORDER:
    1. Sensitive / synthetic gate:
       - Dữ liệu thật / sensitive flags luôn bị chặn fail-closed kể cả no files.
       - Chỉ synthetic explicit mới được đi tiếp.
    2. Adapter verification check:
       - Adapter rỗng ("" / None / whitespace) bị chặn lập tức.
       - Chỉ chấp nhận adapter nằm trong frozen VERIFIED_VISION_ADAPTERS registry (opencode).
    3. Capabilities metadata check (theo model cụ thể).
    4. Kiểm tra file sau gate (synthetic generator-backed):
       - Manifest schema_version=1, generator bench/vision/generate.py.
       - Exact SHA-256 match với pinned trusted registry.
       - Không symlink bất kỳ ancestor nào, không traversal/outside.
    5. Kiểm tra tính tương thích giữa model capabilities và MIME đính kèm.
    """
    # Cờ sensitive hoặc confirmation luôn bị chặn dứt khoát
    if allow_sensitive:
        raise VisionBlockedError(
            "--allow-sensitive-vision is blocked fail-closed; sensitive vision unsupported."
        )
    if confirmation is not None:
        raise VisionBlockedError(
            "Sensitive vision confirmation is blocked; trusted UI unsupported."
        )

    if not files:
        raise VisionFormatError("No attachment files provided for vision")

    # -----------------------------------------------------------------------
    # 1. CỔNG SENSITIVE / SYNTHETIC GATE (TRƯỚC MỌI FILE I/O)
    # -----------------------------------------------------------------------
    if not is_synthetic:
        raise VisionBlockedError(
            "Sensitive or undeclared synthetic vision data is blocked by default. "
            "Sensitive vision is currently unsupported pending trusted UI confirmation."
        )

    # -----------------------------------------------------------------------
    # 2. ADAPTER CHECK (TRƯỚC MỌI FILE I/O)
    # -----------------------------------------------------------------------
    verify_adapter(adapter)

    # -----------------------------------------------------------------------
    # 3. CAPABILITIES CHECK
    # -----------------------------------------------------------------------
    caps = get_model_capabilities(model)

    # -----------------------------------------------------------------------
    # 4. FILE VALIDATION (SYNTHETIC GENERATOR-BACKED CHECK)
    # -----------------------------------------------------------------------
    validated_attachments = validate_synthetic_gate(
        files=files,
        max_bytes=max_bytes,
    )

    # -----------------------------------------------------------------------
    # 5. MODEL CAPABILITY MATCHING
    # -----------------------------------------------------------------------
    has_image = any(att.is_image for att in validated_attachments)
    has_pdf = any(att.is_pdf for att in validated_attachments)

    if has_image and not caps.get("image", False):
        raise VisionBlockedError(f"Model '{model}' does not support image input")

    if has_pdf:
        # Nếu model không hỗ trợ PDF trực tiếp nhưng hỗ trợ image (vd DeepSeek),
        # cho phép để chuyển đổi bằng pdftoppm sau qua prepare_vision_input.
        # Nếu model không hỗ trợ cả PDF lẫn image, lập tức chặn.
        if not caps.get("pdf", False) and not caps.get("image", False):
            raise VisionBlockedError(
                f"Model '{model}' supports neither PDF nor image input"
            )

    return validated_attachments


# ---------------------------------------------------------------------------
# DeepSeek PDF Conversion (pdftoppm)
# ---------------------------------------------------------------------------

def _sanitize_page_prefix(prefix: str) -> str:
    """Chuẩn hoá prefix tên trang: chỉ [A-Za-z0-9_-], tối đa 64 ký tự."""
    safe = _PREFIX_UNSAFE_RE.sub("_", str(prefix or "")).strip("_-")
    safe = safe[:_MAX_PREFIX_LEN].strip("_-")
    return safe or "page"


def _new_private_conversion_dir() -> Path:
    """Tạo thư mục private MỚI trong TMPDIR cho đúng MỘT conversion.

    ``tempfile.mkdtemp`` tạo dir mode 0o700 với tên ngẫu nhiên, không liên quan
    thư mục caller ⇒ bên trong không thể có sẵn file cũ cùng prefix hay symlink
    do người khác đặt.
    """
    return Path(tempfile.mkdtemp(prefix="polykit-vision-"))


def _collect_conversion_pages(out_dir: Path, prefix: str) -> list[Path]:
    """Thu thập output pdftoppm trong private dir — KHÔNG glob, validate từng entry.

    - Chỉ nhận entry khớp CHÍNH XÁC ``<prefix>-<số>.png``.
    - Entry lạ, symlink, non-regular file ⇒ fail-closed (dir private nên bất thường
      không được bỏ qua im lặng).
    - Page id phải liên tục 1..N, N <= ``MAX_CONVERSION_PAGES``.
    - Mỗi trang và tổng output phải > 0 và <= trần; magic bytes phải là PNG.

    Trả về danh sách path theo đúng thứ tự số học 1, 2, ..., N.
    """
    if out_dir.is_symlink() or not out_dir.is_dir():
        raise VisionConversionError("Conversion output directory is not a real directory")

    page_re = re.compile(rf"^{re.escape(prefix)}-(\d+)\.png$")
    found: dict[int, Path] = {}

    try:
        entries = list(os.scandir(out_dir))
    except OSError as e:
        raise VisionConversionError("Cannot read conversion output directory") from e

    for entry in entries:
        match = page_re.match(entry.name)
        if not match:
            raise VisionConversionError(
                "Unexpected entry in private conversion directory"
            )
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            raise VisionConversionError(
                "Conversion output must be a regular non-symlink file"
            )
        try:
            st = entry.stat(follow_symlinks=False)
        except OSError as e:
            raise VisionConversionError("Cannot stat conversion output") from e
        if not stat.S_ISREG(st.st_mode):
            raise VisionConversionError("Conversion output must be a regular file")

        page_no = int(match.group(1))
        if page_no < 1 or page_no in found:
            raise VisionConversionError(
                "Duplicate or invalid page identifier in conversion output"
            )
        if st.st_size <= 0:
            raise VisionConversionError("Conversion produced an empty page image")
        if st.st_size > MAX_CONVERSION_PAGE_BYTES:
            raise VisionConversionError("Converted page exceeds maximum page size")
        found[page_no] = Path(entry.path)

    if not found:
        raise VisionConversionError("pdftoppm produced no image pages")
    if len(found) > MAX_CONVERSION_PAGES:
        raise VisionConversionError(
            f"Conversion produced more than {MAX_CONVERSION_PAGES} pages"
        )

    page_numbers = sorted(found)
    if page_numbers != list(range(1, len(page_numbers) + 1)):
        raise VisionConversionError(
            "Conversion page identifiers are not contiguous starting at 1"
        )

    ordered = [found[n] for n in page_numbers]
    total_bytes = 0
    for page in ordered:
        total_bytes += page.lstat().st_size
        if total_bytes > MAX_CONVERSION_TOTAL_BYTES:
            raise VisionConversionError("Conversion output exceeds maximum total size")
        try:
            with open(page, "rb") as fh:
                header = fh.read(len(PNG_MAGIC))
        except OSError as e:
            raise VisionConversionError("Cannot read converted page") from e
        if not header.startswith(PNG_MAGIC):
            raise VisionConversionError("Converted page is not a PNG image")

    return ordered


def _convert_pdf_to_images(
    pdf_path: str | Path,
    output_dir: str | Path | None = None,
    prefix: str = "page",
    dpi: int = 150,
    timeout: int = 30,
    pdftoppm_bin: str | None = None,
) -> list[Path]:
    """Internal helper for PDF conversion via pdftoppm after vision gate.

    Chỉ được gọi từ prepare_vision_input sau khi đã vượt qua check_vision_gate,
    hoặc gọi trực tiếp trong isolated internal unit tests.

    Quy tắc:
    - Subprocess argv list (không shell=True).
    - Timeout rõ ràng.
    - Không contact sheet; tách trang full res đúng numeric order (1, 2, ..., 10).
    - Thiếu binary pdftoppm phải blocked.
    - Mỗi lần gọi tạo thư mục private MỚI trong TMPDIR; KHÔNG đọc thư mục caller.
    - ``output_dir`` của caller bị reject fail-closed (giữ tham số chỉ để caller cũ
      nhận lỗi rõ ràng thay vì im lặng ghi vào chỗ không an toàn).

    Vòng đời: page PNG nằm trong TMPDIR và được trả về cho bước dispatch dùng
    ngay; module KHÔNG tự xoá (dispatch cần path còn hiệu lực). Caller/hệ điều
    hành dọn TMPDIR sau khi gửi request xong.
    """
    binary = pdftoppm_bin or shutil.which("pdftoppm")
    if not binary:
        raise VisionBlockedError(
            "pdftoppm binary not found. PDF to image conversion blocked."
        )

    if output_dir is not None:
        raise VisionBlockedError(
            "Caller-supplied output_dir is rejected fail-closed; PDF pages are written "
            "only to a fresh private TMPDIR directory per conversion."
        )

    src_pdf = Path(pdf_path)
    if src_pdf.is_symlink():
        raise VisionSecurityError("Symlinks are blocked for PDF conversion source")
    if not src_pdf.exists() or not src_pdf.is_file():
        raise VisionFormatError(f"Source PDF not found: {src_pdf.name}")

    out_dir = _new_private_conversion_dir()
    page_prefix = _sanitize_page_prefix(prefix)
    out_prefix = str(out_dir / page_prefix)

    cmd = [
        str(binary),
        "-png",
        "-r",
        str(dpi),
        str(src_pdf),
        out_prefix,
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise VisionConversionError(
            f"pdftoppm conversion timed out after {timeout}s"
        ) from e
    except OSError as e:
        raise VisionConversionError(
            f"Failed to execute pdftoppm subprocess: {e}"
        ) from e

    if proc.returncode != 0:
        # Không log nội dung hoặc stderr nhạy cảm
        raise VisionConversionError(
            f"pdftoppm exited with nonzero returncode: {proc.returncode}"
        )

    # Chỉ đọc đúng thư mục private vừa tạo, không glob file cũ ở nơi khác.
    return _collect_conversion_pages(out_dir, page_prefix)


def convert_pdf_to_images(
    pdf_path: str | Path,
    output_dir: str | Path,
    prefix: str = "page",
    dpi: int = 150,
    timeout: int = 30,
    pdftoppm_bin: str | None = None,
) -> list[Path]:
    """Public wrapper kept for backward compatibility; blocked fail-closed before any I/O.

    Direct PDF conversion is blocked to prevent un-gated subprocess/file I/O.
    All PDF conversions must proceed via prepare_vision_input after passing check_vision_gate.
    Does not execute pdftoppm_bin or perform any filesystem I/O.
    """
    raise VisionBlockedError(
        "Direct public convert_pdf_to_images is blocked fail-closed before any I/O. "
        "PDF conversion must proceed via gated prepare_vision_input."
    )


# ---------------------------------------------------------------------------
# High-level Preparation API
# ---------------------------------------------------------------------------

def prepare_vision_input(
    files: Sequence[str | Path],
    model: str,
    provider: str = "",
    adapter: str = "",
    is_synthetic: bool = False,
    allow_sensitive: bool = False,
    confirmation: Any = None,
    is_retry: bool = False,
    is_failover: bool = False,
    workspace_root: str | Path | None = None,
    output_dir: str | Path | None = None,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> list[Path]:
    """Inspect files through gate, convert PDF to images if model requires it,
    and return list of final attachment paths ready for dispatch.

    Blocked fail-closed if adapter is blank or unverified, or if data is sensitive.
    Does NOT accept verified_adapters or arbitrary pdftoppm_bin parameters.

    PDF→PNG pages are INTERNAL pipeline artifacts (pdftoppm, private temp dir):
    chúng không phải input tuỳ ý của caller nên không bao giờ đi lại qua
    ``validate_synthetic_gate``. Chỉ danh sách file GỐC do caller khai mới bị
    cổng synthetic kiểm. Vì vậy output nằm trong TMPDIR (không nằm trong repo)
    để không thể bị nhầm là artifact synthetic của generator.

    ``output_dir`` của caller bị REJECT fail-closed (VisionBlockedError) sau khi
    qua cổng: thư mục caller có thể chứa sẵn ``<prefix>-99.png`` cũ hay symlink
    trỏ ra ngoài, nên dùng nó làm đầu ra là mở đường lấy file không do pdftoppm
    sinh. Mỗi conversion luôn nhận thư mục private mới trong TMPDIR.

    Vòng đời: page PNG sống trong TMPDIR và được trả về path cho dispatch dùng
    ngay trong request đó; module không xoá (dispatch cần path còn hiệu lực),
    TMPDIR dọn theo hệ điều hành/caller.
    """
    validated = check_vision_gate(
        files=files,
        model=model,
        provider=provider,
        adapter=adapter,
        is_synthetic=is_synthetic,
        allow_sensitive=allow_sensitive,
        confirmation=confirmation,
        is_retry=is_retry,
        is_failover=is_failover,
        workspace_root=workspace_root,
        max_bytes=max_bytes,
    )

    if output_dir is not None:
        # Gate đã chạy xong mới xét tới tham số này để policy block luôn thắng.
        raise VisionBlockedError(
            "Caller-supplied output_dir is rejected fail-closed; PDF pages are written "
            "only to a fresh private TMPDIR directory per conversion."
        )

    caps = get_model_capabilities(model)
    model_supports_pdf = caps.get("pdf", False)

    final_paths: list[Path] = []

    for att in validated:
        if att.is_pdf and not model_supports_pdf:
            # Model không hỗ trợ PDF trực tiếp (ví dụ DeepSeek) -> tách trang.
            # Mỗi conversion tự tạo private dir riêng, không dùng folder caller.
            pages = _convert_pdf_to_images(
                pdf_path=att.path,
                prefix=att.path.stem,
            )
            final_paths.extend(pages)
        else:
            final_paths.append(att.path)

    return final_paths
