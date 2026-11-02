"""Kiểm artifact kỳ vọng sau khi giao việc GHI FILE (opt-in workspace-write).

Mã thoát vendor CLI không đáng tin (commands/dispatch.md): vendor có thể báo
"đã ghi xong" mà file không có thật. Caller khai `--expect-artifact PATH`
(lặp được) ⇒ sau lượt chạy, PolyKit tự kiểm file có tồn tại VÀ được ghi trong
lượt này (mtime >= lúc bắt đầu) — file cũ còn sót không được tính là bằng chứng.
"""
from __future__ import annotations

from pathlib import Path

# Sai số mtime giữa các filesystem (FAT/SMB làm tròn 2s).
_MTIME_SLACK_S = 2.0


def resolve_artifact(path: str, base: str | None) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path(base or ".").expanduser() / p
    return p.resolve()


def check_artifacts(paths: list[str], base: str | None, since: float) -> tuple[list[str], list[str]]:
    """Trả (ok_lines, problem_lines). problem rỗng ⇒ mọi artifact đạt."""
    ok: list[str] = []
    bad: list[str] = []
    for raw in paths:
        p = resolve_artifact(raw, base)
        if not p.exists():
            bad.append(f"[polykit] artifact_missing: {p} không tồn tại sau lượt chạy")
            continue
        if not p.is_file():
            bad.append(f"[polykit] artifact_missing: {p} không phải file")
            continue
        st = p.stat()
        if st.st_mtime + _MTIME_SLACK_S < since:
            bad.append(f"[polykit] artifact_stale: {p} có sẵn từ trước, không được ghi trong lượt này")
            continue
        ok.append(f"[polykit] artifact ok: {p} ({st.st_size} byte)")
    return ok, bad
