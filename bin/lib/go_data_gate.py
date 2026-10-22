"""Cổng dữ liệu cho lane Go unsandboxed (opencode/hermes) — data_class=code-nopii.

Chốt của Tuan 22/10/2026: opencode/hermes ĐƯỢC chạy KHÔNG sandbox **chỉ** với
việc code / dữ liệu không PII. Cổng này là điều kiện DUY NHẤT, và không có
đường tắt nào khác:

- Caller phải khai báo tường minh ``data_class="code-nopii"`` (CLI
  ``--data-class``, API keyword, builder keyword). Không có cờ → vẫn
  ``sandbox_unsupported`` như trước. Không có tham số bool nào thay thế được.
- Bất kỳ attachment / synthetic_vision / allow_sensitive_vision /
  sensitive_confirmation nào cũng chặn — kể cả khi không có file thật.
- Nếu ``pg-redact`` có trên máy: chạy ``pg-redact check <temp prompt>``.
  Exit khác 0, timeout, hoặc lỗi đều ⇒ blocked (fail-closed). Không bao giờ
  đưa prompt hay output của checker (có thể chứa PII đã che một phần) vào
  result JSON/log.
- Không có ``pg-redact`` → chỉ warning rõ; text code-nopii vẫn chạy được vì
  caller đã khai báo, nhưng attachment vẫn bị cấm tuyệt đối.

``GO_SANDBOX_CONFINED`` **không** phải bypass: hằng số đó chỉ còn là ghi chú
lịch sử, cổng này không đọc nó.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

DATA_CLASS_CODE_NOPII = "code-nopii"
CHECKER_NAME = "pg-redact"
CHECKER_TIMEOUT_S = 20

# Điểm tiêm cho test: patch ``lib.go_data_gate._which`` / ``_checker_runner``.
_which = shutil.which
_checker_runner = subprocess.run


class GoDataGateBlocked(Exception):
    """Cổng dữ liệu Go chặn lượt chạy (trước detector/probe/spawn)."""

    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


def _blocked_no_flag(vendor: str | None) -> GoDataGateBlocked:
    adapter = vendor or "Go adapter"
    return GoDataGateBlocked(
        f"{adapter}: chạy unsandboxed cần khai báo tường minh "
        f"--data-class {DATA_CLASS_CODE_NOPII} (chỉ code/dữ liệu không PII). "
        f"Không có cờ ⇒ sandbox_unsupported, chặn theo Plan mục 83.",
        reason="sandbox_unsupported",
    )


def _blocked_vision(vendor: str | None, detail: str) -> GoDataGateBlocked:
    adapter = vendor or "Go adapter"
    return GoDataGateBlocked(
        f"{adapter}: lane unsandboxed {DATA_CLASS_CODE_NOPII} không nhận "
        f"vision/attachment ({detail}). Cổng vision với dữ liệu thật giữ nguyên chặn.",
        reason="vision_blocked",
    )


def _check_prompt_pii(prompt: str) -> list[str]:
    """Kiểm prompt qua pg-redact. Raise GoDataGateBlocked nếu PII/lỗi/timeout.

    KHÔNG trả và KHÔNG log nội dung prompt hay stdout/stderr của checker.
    """
    checker = _which(CHECKER_NAME)
    if not checker:
        return [
            f"[polykit] không tìm thấy {CHECKER_NAME} trên máy — KHÔNG kiểm được PII; "
            f"lane Go vẫn chạy vì caller đã khai báo data_class={DATA_CLASS_CODE_NOPII}, "
            f"nhưng attachment/vision vẫn bị cấm tuyệt đối."
        ]

    # TMPDIR: tempfile.gettempdir() tôn trọng TMPDIR trên mọi OS.
    fd, path = tempfile.mkstemp(prefix="polykit-pii-", suffix=".txt",
                                dir=tempfile.gettempdir())
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(prompt)
        try:
            res = _checker_runner(
                [checker, "check", path],
                capture_output=True,
                text=True,
                timeout=CHECKER_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            raise GoDataGateBlocked(
                f"{CHECKER_NAME} check quá {CHECKER_TIMEOUT_S}s — fail-closed, "
                f"không chạy vendor (không in prompt/checker output).",
                reason="pii_checker_failed",
            )
        except Exception as exc:  # noqa: BLE001 — mọi lỗi đều fail-closed
            raise GoDataGateBlocked(
                f"{CHECKER_NAME} check lỗi ({type(exc).__name__}) — fail-closed, "
                f"không chạy vendor (không in prompt/checker output).",
                reason="pii_checker_failed",
            )
        if res.returncode != 0:
            # Không kèm stdout/stderr: chúng có thể chứa PII đã che một phần.
            raise GoDataGateBlocked(
                f"{CHECKER_NAME} check exit {res.returncode} (phát hiện PII hoặc "
                f"từ chối kiểm) — blocked trước detector/probe/vendor spawn; "
                f"không in prompt/checker output.",
                reason="pii_detected",
            )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return []


def _reject_shadow_repo(workdir: str | None, vendor: str | None) -> None:
    """Chặn ``--cd`` trỏ vào một cây KHÁC có synthetic manifest riêng.

    Artifact synthetic luôn đọc từ ``REAL_REPO_ROOT`` nên workdir không mở được
    cổng; nhưng một "repo giả" (copy cây repo + manifest tự viết) là dấu hiệu
    caller đang cố lái cổng sang dữ liệu khác ⇒ chặn trước khi chạm file.
    Workdir là repo thật (hoặc con của nó) vẫn hợp lệ; workdir thường cũng hợp lệ.
    """
    if not workdir:
        return
    try:
        from pathlib import Path
        from lib.vision import REAL_REPO_ROOT
    except ImportError:
        from pathlib import Path
        from bin.lib.vision import REAL_REPO_ROOT
    try:
        wd = Path(workdir).resolve(strict=False)
    except (OSError, RuntimeError):
        return
    real = Path(REAL_REPO_ROOT).resolve(strict=False)
    if wd == real or real in wd.parents:
        return
    if (wd / "bench" / "vision" / "synthetic" / "manifest.json").is_file():
        raise _blocked_vision(
            vendor, "workdir trỏ vào cây khác có synthetic manifest (repo giả)"
        )


def _assert_model_accepts_vision(
    model: str | None, attachments: list[str], vendor: str | None
) -> None:
    """Model phải là model đã biết VÀ có khả năng nhận input ảnh/PDF.

    Chạy trước synthetic gate để một model không nhận vision (hoặc slug lạ
    ``auto``) không bao giờ đi tới bước đọc/hash file.
    """
    try:
        from lib.vision import get_model_capabilities, VisionError
    except ImportError:
        from bin.lib.vision import get_model_capabilities, VisionError
    if not model or not isinstance(model, str):
        raise _blocked_vision(vendor, "model chưa resolve cho vision (cần slug cụ thể)")
    try:
        caps = get_model_capabilities(model)
    except VisionError as exc:
        raise _blocked_vision(vendor, f"model {model!r} chưa xác minh vision: {exc}") from exc
    if not caps.get("image", False) and not caps.get("pdf", False):
        raise _blocked_vision(vendor, f"model {model!r} không nhận image/pdf")


def evaluate_go_data_gate(
    *,
    data_class: str | None,
    prompt: str,
    attachments: list[str] | None = None,
    synthetic_vision: bool = False,
    allow_sensitive_vision: bool = False,
    sensitive_confirmation: object = None,
    vendor: str | None = None,
    model: str | None = None,
    workdir: str | None = None,
) -> list[str]:
    """Trả warnings khi được phép chạy; raise GoDataGateBlocked khi bị chặn.

    Thứ tự kiểm: cờ data_class → vision/sensitive flags → workdir giả repo →
    policy vision theo vendor → capability model → synthetic generator gate →
    PII checker.

    ``model``/``workdir`` là tham số ĐỘC LẬP với ``attachments``: builder và
    dispatcher đều truyền xuống nên cổng không phụ thuộc một boolean nào của
    caller. ``workdir`` KHÔNG được dùng để suy ra repo gốc (artifact synthetic
    luôn đọc từ ``REAL_REPO_ROOT``); nó chỉ bị kiểm để chặn "repo giả" do
    ``--cd`` trỏ vào một cây khác có manifest riêng.
    """
    if data_class != DATA_CLASS_CODE_NOPII:
        raise _blocked_no_flag(vendor)

    # Dữ liệu thật / sensitive flags luôn block kể cả no files
    if allow_sensitive_vision:
        raise _blocked_vision(vendor, "allow_sensitive_vision")
    if sensitive_confirmation is not None:
        raise _blocked_vision(vendor, "sensitive_confirmation")

    # --cd/workdir trỏ vào repo khác có manifest synthetic riêng = repo giả
    _reject_shadow_repo(workdir, vendor)

    # Kiểm tra vision / attachment cho từng vendor
    if vendor == "hermes":
        # hermes giữ block nếu helper chưa support
        if attachments or synthetic_vision:
            raise _blocked_vision(vendor, "synthetic_vision unsupported on hermes")
    elif vendor == "opencode":
        if attachments:
            if not synthetic_vision:
                raise _blocked_vision(vendor, f"{len(attachments)} attachment without --synthetic-vision")
            _assert_model_accepts_vision(model, attachments, vendor)
            # Validate synthetic attachments độc lập qua generator gate (không boolean bypass)
            try:
                from lib.vision import validate_synthetic_gate, VisionError
            except ImportError:
                from bin.lib.vision import validate_synthetic_gate, VisionError
            try:
                validate_synthetic_gate(attachments)
            except VisionError as exc:
                raise _blocked_vision(vendor, f"synthetic vision validation failed: {exc}") from exc
        elif synthetic_vision:
            raise _blocked_vision(vendor, "synthetic_vision declared without attachments")
    else:
        if attachments or synthetic_vision:
            raise _blocked_vision(vendor, f"{vendor or 'Go adapter'} does not support vision attachments")

    return _check_prompt_pii(prompt)
