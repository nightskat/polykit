"""BUG-11 (20/08/2026): chạy pytest bơm bản ghi vào LOG THẬT của người dùng.

Đo được: mỗi lượt `pytest -q` thêm 8 dòng vào
`~/Library/Application Support/polykit/dispatch-log.jsonl`, trong đó có bản ghi
mang tên vendor THẬT (`claude`). Từ khi BUG-4 cho `doctor` suy trạng thái quota
từ chính log này, rác của test không còn vô hại.
"""
import os
from pathlib import Path

from lib.evidence import evidence_path
from lib.paths import user_state_dir


def test_log_evidence_khi_chay_test_KHONG_tro_vao_thu_muc_that():
    p = str(evidence_path())
    that = str(Path.home() / "Library" / "Application Support" / "polykit")
    assert that not in p, f"test đang ghi vào log thật: {p}"
    assert os.environ.get("XDG_STATE_HOME"), "conftest phải cô lập XDG_STATE_HOME"
    assert os.environ["XDG_STATE_HOME"] in str(user_state_dir("polykit"))
