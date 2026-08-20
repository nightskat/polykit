"""BUG-9 phần còn lại (20/08/2026): 3 đường vẫn nuốt lỗi thật sau khi vá nhánh timeout.

  (2) returncode == 0  → trả `ok` ngay, stderr bị vứt sạch.
  (3) lane gemini      → không đi qua _classify_completed, chỉ còn "lane N failed" trơ.
  (4) vendor ghi lỗi ra STDOUT (rõ nhất ở --json) → mọi phép dò trên stderr đều mù.
"""
from types import SimpleNamespace

from lib.dispatcher import _classify_completed


def _res(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


# ── (2) exit 0 vẫn phải giữ cảnh báo ────────────────────────────────────────

def test_exit0_van_giu_canh_bao_tren_stderr():
    r = _classify_completed("codex", "gpt-5.5",
                            _res(stdout="kết quả", stderr="warning: quota còn 5%"))
    assert r.status == "ok" and r.stdout == "kết quả"
    assert any("quota còn 5%" in w for w in r.warnings), "cảnh báo lúc exit 0 bị vứt"


def test_exit0_sach_thi_khong_de_rac_vao_warnings():
    r = _classify_completed("codex", "gpt-5.5", _res(stdout="kết quả", stderr="   \n"))
    assert r.status == "ok" and r.warnings == []


def test_exit0_khong_doc_echo_prompt_thanh_canh_bao():
    prompt = "phân tích hộ tôi"
    r = _classify_completed("codex", "auto",
                            _res(stdout="xong", stderr="phân tích hộ tôi"), prompt=prompt)
    assert r.warnings == []


# ── (4) lỗi nằm ở stdout ────────────────────────────────────────────────────

ERR_JSON = '{"error":{"message":"invalid api key"}}'


def test_loi_ghi_ra_stdout_van_lo_ra_duoc():
    r = _classify_completed("codex", "auto", _res(returncode=1, stdout=ERR_JSON, stderr=""))
    assert r.status == "error"
    assert any("invalid api key" in w for w in r.warnings), "lỗi ở stdout vẫn bị mù"
    assert any("lấy từ STDOUT" in w for w in r.warnings), "phải nói rõ dấu vết lấy từ đâu"


def test_quota_ghi_ra_stdout_van_thanh_quota_capped():
    r = _classify_completed("grok", "auto",
                            _res(returncode=1, stdout="You've hit your usage limit", stderr=""))
    assert r.status == "skipped" and r.reason == "quota_capped"


def test_stderr_co_nhung_VO_DUNG_thi_van_phai_lay_them_stdout():
    """Ca live 20/08: `codex --format json` để stderr đúng một dòng vô dụng,
    lỗi thật nằm trong stdout. Guard 'chỉ khi stderr rỗng' trượt ca này."""
    r = _classify_completed("codex", "auto",
                            _res(returncode=1, stdout=ERR_JSON,
                                 stderr="Reading prompt from stdin..."))
    assert any("invalid api key" in w for w in r.warnings), "lỗi ở stdout vẫn bị mù"
    assert any("Reading prompt" in w for w in r.warnings), "vẫn giữ cả stderr"


def test_giu_ca_hai_nguon_va_ghi_ro_nguon():
    r = _classify_completed("codex", "auto",
                            _res(returncode=1, stdout="nửa bài viết", stderr="ERROR: hỏng thật"))
    assert any("hỏng thật" in w for w in r.warnings)
    assert any("lấy từ STDOUT" in w for w in r.warnings)


def test_cha_in_gi_ca_thi_noi_ro_chu_khong_de_rong():
    r = _classify_completed("codex", "auto", _res(returncode=1))
    assert r.warnings and "không in gì" in r.warnings[0]
