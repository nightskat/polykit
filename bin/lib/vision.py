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
5. Privacy:
   - Tuyệt đối không log nội dung file hay PII trong log/error.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
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


class VisionSecurityError(VisionError):
    """Raised on security violations: symlink, path traversal, or workspace escape."""
    pass


class VisionFormatError(VisionError):
    """Raised on invalid format, MIME signature mismatch, missing file, or empty file."""
    pass


class VisionQuotaError(VisionError):
    """Raised when file size exceeds limits."""
    pass


class VisionConversionError(VisionError):
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
# Module API không tự enable adapter — hằng frozen registry mặc định trống (fail-closed).
VERIFIED_VISION_ADAPTERS: frozenset[str] = frozenset()

# MIME Magic Signatures
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
PDF_MAGIC = b"%PDF"

SUPPORTED_MIME_TYPES = {
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "application/pdf": {".pdf"},
}


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
# Core Vision Gate
# ---------------------------------------------------------------------------

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
       - Nếu không tuyên bố is_synthetic=True rõ ràng:
         * Blocked mặc định.
         * Không chấp nhận string bất kỳ làm consent.
         * Cờ allow_sensitive không đủ nếu thiếu confirmation.
         * Confirmation không kế thừa retry/failover.
         * Vì chưa có UI xác nhận Tuan đáng tin, sensitive luôn blocked fail-closed.
       - TUYỆT ĐỐI không gọi stat/open/exists/subprocess nếu bị chặn ở cổng này!
    2. Adapter verification check:
       - Adapter rỗng ("" / None / whitespace) bị chặn lập tức.
       - Chỉ chấp nhận adapter nằm trong frozen VERIFIED_VISION_ADAPTERS registry.
       - Không nhận tham số verified_adapters tự chứng thực.
       - Chặn TRƯỚC mọi file stat, open, probe.
    3. Capabilities metadata check (theo model cụ thể).
    4. Kiểm tra file sau gate (chỉ với synthetic explicit):
       - Path thường, không symlink, trong workspace, MIME signature, dung lượng.
    5. Kiểm tra tính tương thích giữa model capabilities và MIME đính kèm.
    """
    if not files:
        raise VisionFormatError("No attachment files provided for vision")

    # -----------------------------------------------------------------------
    # 1. CỔNG SENSITIVE / SYNTHETIC GATE (TRƯỚC MỌI FILE I/O)
    # -----------------------------------------------------------------------
    if not is_synthetic:
        # Kiểm tra string consent bị từ chối dứt khoát
        if isinstance(confirmation, str):
            raise VisionBlockedError(
                "Arbitrary string consent is rejected. Sensitive vision blocked."
            )

        # Cờ allow_sensitive một mình không đủ
        if allow_sensitive and confirmation is None:
            raise VisionBlockedError(
                "--allow-sensitive-vision alone is not sufficient without confirmation. "
                "Sensitive vision blocked."
            )

        # Confirmation kiểm tra
        if isinstance(confirmation, SingleTurnConfirmation):
            valid, reason = confirmation.is_valid_for(
                files=files,
                model=model,
                provider=provider,
                is_retry=is_retry,
                is_failover=is_failover,
            )
            if not valid:
                raise VisionBlockedError(
                    f"Sensitive vision confirmation invalid ({reason}); blocked."
                )
            # Vì chưa có UI xác nhận Tuan đáng tin
            if not confirmation.is_trusted_ui:
                raise VisionBlockedError(
                    "Sensitive vision blocked: trusted UI confirmation is not supported yet."
                )

        # Mặc định fail-closed cho mọi dữ liệu không phải explicit synthetic
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
    # 4. FILE VALIDATION (CHỈ KHI ĐÃ QUA GATE VÀ LÀ SYNTHETIC EXPLICIT)
    # -----------------------------------------------------------------------
    ws = Path(workspace_root) if workspace_root else Path.cwd()
    validated_attachments: list[VisionAttachment] = []

    for item in files:
        if not item:
            raise VisionFormatError("Empty file path provided")
        path_obj = Path(item)
        attachment = validate_file_format(
            path=path_obj,
            workspace_root=ws,
            max_bytes=max_bytes,
        )
        validated_attachments.append(attachment)

    # -----------------------------------------------------------------------
    # 5. MODEL CAPABILITY MATCHING
    # -----------------------------------------------------------------------
    has_image = any(att.is_image for att in validated_attachments)
    has_pdf = any(att.is_pdf for att in validated_attachments)

    if has_image and not caps.get("image", False):
        raise VisionBlockedError(f"Model '{model}' does not support image input")

    if has_pdf:
        # Nếu model không hỗ trợ PDF trực tiếp nhưng hỗ trợ image,
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

def _natural_page_sort_key(file_path: Path) -> int:
    """Extract page number from filename for natural numeric sorting.

    Examples:
      prefix-1.png -> 1
      prefix-2.png -> 2
      prefix-10.png -> 10
    """
    m = re.search(r"[-_](\d+)\.(?:png|jpe?g)$", file_path.name, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 0


def _convert_pdf_to_images(
    pdf_path: str | Path,
    output_dir: str | Path,
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
    """
    binary = pdftoppm_bin or shutil.which("pdftoppm")
    if not binary:
        raise VisionBlockedError(
            "pdftoppm binary not found. PDF to image conversion blocked."
        )

    src_pdf = Path(pdf_path)
    if not src_pdf.exists() or not src_pdf.is_file():
        raise VisionFormatError(f"Source PDF not found: {src_pdf.name}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_prefix = str(out_dir / prefix)

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

    # Thu thập các trang đã sinh và sắp xếp theo thứ tự số học tự nhiên
    generated = list(out_dir.glob(f"{prefix}-*.png"))
    if not generated:
        raise VisionConversionError("pdftoppm produced no image pages")

    generated.sort(key=_natural_page_sort_key)
    return generated


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

    caps = get_model_capabilities(model)
    model_supports_pdf = caps.get("pdf", False)

    final_paths: list[Path] = []
    ws = Path(workspace_root) if workspace_root else Path.cwd()

    for att in validated:
        if att.is_pdf and not model_supports_pdf:
            # Model không hỗ trợ PDF trực tiếp (ví dụ DeepSeek) -> Tách từng trang thành ảnh qua private helper
            conv_dir = Path(output_dir) if output_dir else ws / ".vision_converted"
            pages = _convert_pdf_to_images(
                pdf_path=att.path,
                output_dir=conv_dir,
                prefix=att.path.stem,
            )
            final_paths.extend(pages)
        else:
            final_paths.append(att.path)

    return final_paths
