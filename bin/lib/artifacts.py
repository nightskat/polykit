"""Kiểm artifact kỳ vọng sau khi giao việc GHI FILE (opt-in workspace-write).

Mã thoát vendor CLI không đáng tin (commands/dispatch.md): vendor có thể báo
"đã ghi xong" mà file không có thật. Caller khai `--expect-artifact PATH`
(lặp được) ⇒ sau lượt chạy, PolyKit tự kiểm file có tồn tại VÀ được ghi trong
lượt này (mtime >= lúc bắt đầu) — file cũ còn sót không được tính là bằng chứng.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

# Sai số mtime giữa các filesystem (FAT/SMB làm tròn 2s).
_MTIME_SLACK_S = 2.0


def resolve_artifact(path: str, base: str | None) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path(base or ".").expanduser() / p
    return p.resolve()


def _digest(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_artifacts(paths: list[str], base: str | None) -> dict[str, str | None]:
    """Chụp sha256 nội dung TRƯỚC lượt chạy: file có sẵn mà nội dung không đổi = cũ
    (so mtime thôi thì file cũ bị `touch` vẫn lọt)."""
    snap: dict[str, str | None] = {}
    for raw in paths:
        p = resolve_artifact(raw, base)
        try:
            snap[str(p)] = _digest(p) if p.is_file() else None
        except OSError:
            snap[str(p)] = None
    return snap


def check_artifacts(paths: list[str], base: str | None, since: float,
                    before: dict[str, str | None] | None = None) -> tuple[list[str], list[str]]:
    """Trả (ok_lines, problem_lines). problem rỗng ⇒ mọi artifact đạt.

    Có `before` (snapshot trước lượt chạy) ⇒ so sha256 nội dung: file có sẵn
    mà nội dung không đổi (kể cả bị touch) = stale, bất kể slack filesystem. Không có ⇒ fallback
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
            stale = prev is not None and _digest(p) == prev
        else:
            stale = st.st_mtime + _MTIME_SLACK_S < since
        if stale:
            bad.append(f"[polykit] artifact_stale: {p} có sẵn từ trước, không được ghi trong lượt này")
            continue
        ok.append(f"[polykit] artifact ok: {p} ({st.st_size} byte)")
    return ok, bad
