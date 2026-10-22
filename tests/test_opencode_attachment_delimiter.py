"""Regression Lô2d: opencode `-f` variadic nuốt prompt ⇒ thiếu `--` delimiter.

Live bug (vision dispatch): mọi lượt vision chết `exit 1` với
``Error: File not found: <toàn bộ prompt>``.

Nguyên nhân: `opencode run` khai báo ``-f/--file`` là **array** và ``message``
là **positional array**. Khi argv là ``... -f a.png -f b.png <prompt>``, yargs
gom ``<prompt>`` thành phần tử ``-f`` thứ ba, coi nó là đường dẫn file ⇒ vendor
trả "File not found: <prompt>" và không bao giờ chạy.

Đã xác minh trực tiếp trên CLI thật (opencode 1.x, `opencode run --help`):
  - ``opencode run -m … -f a.txt -f b.txt "PROMPT_XYZ"``
        → ``Error: File not found: PROMPT_XYZ``
  - ``opencode run -m … -f a.txt -f b.txt -- "PROMPT_XYZ"``
        → chạy thật, model trả lời

Hợp đồng được khoá ở đây:
1. ``--`` đứng NGAY sau flags/files và NGAY trước prompt.
2. Prompt luôn là phần tử cuối, positional, kể cả khi bắt đầu bằng ``-``.
3. Thứ tự attachment giữ nguyên; mỗi file vẫn là một cặp ``-f <path>``.
4. Không attachment vẫn có ``--`` (prompt bắt đầu ``-`` không bị đọc thành flag).
5. Policy/gate KHÔNG bị nới: contributor vẫn chặn, attachment phi-synthetic vẫn
   ``vision_blocked``, workdir/model/variant giữ nguyên.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import lib.dispatch_core as dc
from lib.dispatch_core import (
    DispatchError,
    DispatchContributorBlocked,
    _build_opencode_argv,
)

MODEL = "deepseek-v4.1-flash"
DATA_CLASS = "code-nopii"
SYNTHETIC_DIR = Path(__file__).resolve().parent.parent / "bench" / "vision" / "synthetic"
PNG_A = SYNTHETIC_DIR / "page_01_narrow_table.png"
PNG_B = SYNTHETIC_DIR / "page_02_negative_numbers.png"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_two_attachments(prompt: str, **kwargs) -> list[str]:
    """Dựng argv qua gate thật (manifest + registry), không mock."""
    return _build_opencode_argv(
        MODEL,
        prompt,
        attachments=[str(PNG_A), str(PNG_B)],
        synthetic_vision=True,
        data_class=DATA_CLASS,
        **kwargs,
    )


def _prompt_view(cmd: list[str]) -> list[str]:
    """Phần argv sau ``--`` — đúng những gì vendor nhận là message positionals."""
    assert "--" in cmd, f"thiếu delimiter '--' trong argv: {cmd}"
    return cmd[cmd.index("--") + 1:]


def _file_args(cmd: list[str]) -> list[str]:
    """Các path đi kèm -f, dừng ở delimiter."""
    stop = cmd.index("--") if "--" in cmd else len(cmd)
    out: list[str] = []
    i = 0
    while i < stop:
        if cmd[i] in ("-f", "--file"):
            out.append(cmd[i + 1])
            i += 2
        else:
            i += 1
    return out


# ---------------------------------------------------------------------------
# 1. Hợp đồng delimiter
# ---------------------------------------------------------------------------

def test_hai_attachment_co_delimiter_ngay_truoc_prompt():
    prompt = "Đọc hai trang scan và trả JSON ground truth."
    cmd = _build_two_attachments(prompt)

    assert cmd[-1] == prompt, "prompt phải là phần tử cuối"
    assert cmd[-2] == "--", "delimiter phải đứng ngay trước prompt"
    assert _prompt_view(cmd) == [prompt], "prompt không được bị cắt thành array"


def test_f_va_delimiter_dung_thu_tu():
    prompt = "vision task"
    cmd = _build_two_attachments(prompt)

    # cặp -f cho từng file, giữ đúng thứ tự input
    assert _file_args(cmd) == [str(PNG_A), str(PNG_B)]
    # mọi -f nằm TRƯỚC delimiter
    last_f = max(i for i, tok in enumerate(cmd) if tok == "-f")
    assert last_f < cmd.index("--")
    # và delimiter đứng ngay sau file cuối
    assert cmd[last_f + 2] == "--"


def test_prompt_bat_dau_bang_dash_van_la_positional():
    """Prompt kiểu '-kiểm tra page 1' không được parse thành flag."""
    prompt = "-đọc trang 1, trả JSON"
    cmd = _build_two_attachments(prompt)

    assert cmd[-1] == prompt
    assert cmd[-2] == "--"
    assert _prompt_view(cmd) == [prompt]


def test_prompt_chua_dash_dash_khong_bi_cat():
    """Prompt có literal '--' bên trong vẫn là MỘT argv element."""
    prompt = "diff --stat rồi giải thích"
    cmd = _build_two_attachments(prompt)

    assert cmd.count("--") == 1, "chỉ có đúng delimiter của builder"
    assert _prompt_view(cmd) == [prompt]


def test_khong_attachment_van_co_delimiter():
    """Đường text-only cũng phải có '--' để prompt '-x' không thành flag."""
    cmd = _build_opencode_argv(MODEL, "-không phải flag", data_class=DATA_CLASS)

    assert cmd[-1] == "-không phải flag"
    assert cmd[-2] == "--"
    assert _file_args(cmd) == []


def test_delimiter_khong_lam_mat_flag_truoc_do():
    prompt = "task"
    cmd = _build_opencode_argv(
        MODEL, prompt, effort="high", fmt="json",
        attachments=[str(PNG_A), str(PNG_B)], synthetic_vision=True,
        data_class=DATA_CLASS,
    )

    assert cmd[1] == "run"
    assert cmd[cmd.index("--model") + 1] == f"opencode-go/{MODEL}"
    assert cmd[cmd.index("--variant") + 1] == "high"
    assert cmd[cmd.index("--format") + 1] == "json"
    assert cmd[-2:] == ["--", prompt]


# ---------------------------------------------------------------------------
# 2. Preserve order / workdir / policy gates
# ---------------------------------------------------------------------------

def test_thu_tu_hai_attachment_giu_nguyen_va_workdir_khong_doi_argv():
    """workdir đi vào gate, không tự chen flag lạ vào argv."""
    cwd_before = Path.cwd()
    cmd = _build_two_attachments("task", workdir=str(cwd_before))

    assert _file_args(cmd) == [str(PNG_A), str(PNG_B)]
    assert "--dir" not in cmd, "builder không tự thêm --dir ngoài hợp đồng"
    assert cmd[-2:] == ["--", "task"]


def test_attachment_khong_synthetic_van_bi_chan_truoc_argv():
    """Không được lấy cớ 'thêm --' để nới cổng vision."""
    with pytest.raises(DispatchError) as exc:
        _build_opencode_argv(
            MODEL, "task",
            attachments=[str(PNG_A), str(PNG_B)],
            data_class=DATA_CLASS,
        )
    assert exc.value.reason == "vision_blocked"


def test_file_khong_ton_tai_van_bi_chan():
    with pytest.raises(DispatchError) as exc:
        _build_opencode_argv(
            MODEL, "task",
            attachments=["/tmp/khong-ton-tai-polykit-xyz.png"],
            synthetic_vision=True,
            data_class=DATA_CLASS,
        )
    assert exc.value.reason == "vision_blocked"


def test_contributor_van_bi_chan_khi_co_attachment():
    with pytest.raises(DispatchContributorBlocked):
        _build_opencode_argv(
            f"{MODEL}-contributor", "task",
            attachments=[str(PNG_A)], synthetic_vision=True,
            data_class=DATA_CLASS,
        )
