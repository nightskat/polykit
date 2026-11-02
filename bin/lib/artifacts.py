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


def snapshot_artifacts(paths: list[str], base: str | None) -> dict[str, int | None]:
    """Chụp mtime_ns TRƯỚC lượt chạy: file có sẵn mà mtime không đổi = cũ."""
    snap: dict[str, int | None] = {}
    for raw in paths:
        p = resolve_artifact(raw, base)
        try:
            snap[str(p)] = p.stat().st_mtime_ns
        except OSError:
            snap[str(p)] = None
    return snap


def check_artifacts(paths: list[str], base: str | None, since: float,
                    before: dict[str, int | None] | None = None) -> tuple[list[str], list[str]]:
    """Trả (ok_lines, problem_lines). problem rỗng ⇒ mọi artifact đạt.

    Có `before` (snapshot trước lượt chạy) ⇒ so mtime_ns chính xác: file có sẵn
    mà mtime không đổi = stale, bất kể slack filesystem. Không có ⇒ fallback
    so với `since` kèm slack."""
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
        if before is not None and str(p) in before:
            prev = before[str(p)]
            stale = prev is not None and st.st_mtime_ns == prev
        else:
            stale = st.st_mtime + _MTIME_SLACK_S < since
        if stale:
            bad.append(f"[polykit] artifact_stale: {p} có sẵn từ trước, không được ghi trong lượt này")
            continue
        ok.append(f"[polykit] artifact ok: {p} ({st.st_size} byte)")
    return ok, bad
