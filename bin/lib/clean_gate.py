"""Cổng `--require-clean` (opt-in): prompt phải qua checker PII trước MỌI probe/spawn.

docs/BUGS.md QUAN SÁT-3: luật lane PGBank bắt `pg-redact check` exit 0 trước
khi gửi, nhưng chỉ còn kỷ luật tay. Cờ này biến luật đó thành cổng cứng — CHỈ
khi caller opt-in (pg-redact còn hỏng với văn xuôi nên chưa bật mặc định).

Fail-closed tuyệt đối khi đã opt-in:
- Không tìm thấy checker      ⇒ blocked (reason ``clean_checker_missing``)
- Checker exit != 0           ⇒ blocked (reason ``pii_detected``)
- Timeout / lỗi chạy checker  ⇒ blocked (reason ``clean_check_failed``)
KHÔNG bao giờ đưa prompt hay stdout/stderr của checker vào result/log.

Điểm tiêm (mock): patch ``lib.clean_gate._which`` / ``_checker_runner``, hoặc
đặt env ``POLYKIT_CLEAN_CHECKER=<đường dẫn checker>`` (dùng cho test subprocess
với checker giả). Giao thức checker: ``<checker> check <file-prompt>`` → exit 0 = sạch.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

CHECKER_NAME = "pg-redact"
CHECKER_ENV = "POLYKIT_CLEAN_CHECKER"
CHECKER_TIMEOUT_S = 20

_which = shutil.which
_checker_runner = subprocess.run


class CleanGateBlocked(Exception):
    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


def _find_checker() -> str | None:
    override = os.environ.get(CHECKER_ENV)
    if override:
        return override if os.path.isfile(override) else None
    return _which(CHECKER_NAME)


def require_clean(prompt: str) -> list[str]:
    """Raise CleanGateBlocked nếu không chứng minh được prompt sạch. Trả warnings."""
    checker = _find_checker()
    if not checker:
        raise CleanGateBlocked(
            f"--require-clean: không tìm thấy checker ({CHECKER_NAME} hoặc ${CHECKER_ENV}) — "
            f"fail-closed, chưa probe/spawn vendor.",
            reason="clean_checker_missing",
        )
    fd, path = tempfile.mkstemp(prefix="polykit-clean-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(prompt)
        try:
            res = _checker_runner([checker, "check", path], capture_output=True,
                                  text=True, timeout=CHECKER_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise CleanGateBlocked(
                f"--require-clean: checker quá {CHECKER_TIMEOUT_S}s — fail-closed.",
                reason="clean_check_failed")
        except Exception as exc:  # noqa: BLE001 — mọi lỗi đều fail-closed
            raise CleanGateBlocked(
                f"--require-clean: checker lỗi ({type(exc).__name__}) — fail-closed.",
                reason="clean_check_failed")
        if res.returncode != 0:
            raise CleanGateBlocked(
                f"--require-clean: checker exit {res.returncode} (phát hiện PII hoặc từ chối) — "
                f"blocked trước probe/spawn; không in prompt/checker output.",
                reason="pii_detected")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return [f"[polykit] --require-clean: prompt qua checker {os.path.basename(checker)} (exit 0)."]
