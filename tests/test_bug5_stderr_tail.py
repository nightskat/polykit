"""BUG-5 (đo 20/08/2026): `--result-json` nuốt mất dòng lỗi thật của vendor.

Hai khuyết tật độc lập, cùng gây ra một triệu chứng `exit_code=1` trơ:
  1. `warnings` lấy 20 dòng ĐẦU của stderr — codex in banner + echo prompt trước,
     nên dòng ERROR thật bị đẩy ra ngoài cửa sổ.
  2. Mẫu quota không khớp nguyên văn của codex ("You've hit your usage limit"),
     nên hết quota bị xếp thành vendor_exit_nonzero và failover đi sai nhánh.
"""
from types import SimpleNamespace

from lib.dispatch_core import build_codex_cmd
from lib.dispatcher import (STDERR_HEAD, STDERR_KEEP, _classify_completed,
                            strip_echoed_prompt, tail_lines)
from lib.quota_error import is_quota_error


def _res(returncode=1, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


# ── 1. giữ đuôi, không giữ đầu ───────────────────────────────────────────────

def test_tail_lines_giu_dong_cuoi_va_banner_dau():
    stderr = "\n".join([f"banner {i}" for i in range(50)] + ["ERROR: lỗi thật ở đây"])
    out = tail_lines(stderr)
    assert out[-1] == "ERROR: lỗi thật ở đây"       # lỗi ở cuối: giữ
    assert out[0] == "banner 0"                      # banner version/model: giữ
    assert "banner 25" not in out                    # khúc giữa: bỏ
    assert any(w.startswith("[polykit]") for w in out)   # có ghi rõ bỏ bao nhiêu
    assert len(out) == STDERR_HEAD + 1 + STDERR_KEEP


def test_tail_lines_bien_vua_du_thi_khong_cat():
    """Biên len == head+keep: giữ nguyên, không chèn dòng '…bỏ 0 dòng'."""
    lines = [f"d{i}" for i in range(STDERR_HEAD + STDERR_KEEP)]
    out = tail_lines("\n".join(lines))
    assert out == lines


def test_tail_lines_ngan_thi_giu_nguyen_khong_them_dong_thua():
    stderr = "một dòng\nhai dòng"
    assert tail_lines(stderr) == ["một dòng", "hai dòng"]


def test_loi_that_song_sot_qua_classify_khi_prompt_dai_bi_echo():
    """Tái lập đúng ca 20/08: banner + echo prompt dài, ERROR nằm cuối."""
    stderr = "\n".join(
        ["OpenAI Codex v0.148.0", "workdir: /x", "model: gpt-5.5"]
        + [f"dòng prompt {i}" for i in range(60)]
        + ['ERROR: {"status":400,"message":"model không hỗ trợ"}']
    )
    r = _classify_completed("codex", "gpt-5.5", _res(stderr=stderr))
    assert r.status == "error"
    assert any("model không hỗ trợ" in w for w in r.warnings), r.warnings


# ── 2. nhận đúng chữ codex/gemini thật sự in ra ──────────────────────────────

def test_nhan_dien_nguyen_van_codex_het_quota():
    stderr = ("ERROR: You've hit your usage limit. Upgrade to Pro ... "
              "try again at Aug 20th, 2026 10:58 AM.")
    assert is_quota_error(stderr, 1)
    r = _classify_completed("codex", "gpt-5.5", _res(stderr=stderr))
    assert r.status == "skipped"
    assert r.reason == "quota_capped"


def test_nhan_dien_nguyen_van_gemini_het_quota():
    assert is_quota_error("TerminalQuotaError: You have exhausted your daily quota on this model.", 1)


def test_khong_bat_nham_van_ban_thuong():
    """Mẫu mới không được nuốt câu bình thường có chữ 'limit' hay 'quota'."""
    for s in ["đã đặt limit cho vòng lặp", "hàm quota_report() trả về 0", "rate limiting middleware"]:
        assert not is_quota_error(s, 1), s


# ── 3. ba ca test codex chỉ ra còn thiếu ở bản vá --skip-git-repo-check ──────

def test_workdir_van_co_co_khi_text_va_auto():
    cmd = build_codex_cmd(model="auto", sandbox="read-only", workdir="/khong-phai-git", fmt="text")
    assert "--skip-git-repo-check" in cmd
    assert cmd[cmd.index("-C") + 1] == "/khong-phai-git"


def test_chi_co_dung_MOT_co_skip_git():
    for wd in (None, "/x"):
        for fmt in ("text", "json"):
            cmd = build_codex_cmd(model="auto", sandbox="read-only", workdir=wd, fmt=fmt)
            assert cmd.count("--skip-git-repo-check") == 1, cmd


# ── 4. KHÔNG được đọc chính chữ của mình (DeepSeek chỉ ra, đã đo: codex echo
#     prompt ra stderr ở dòng 13-14) ────────────────────────────────────────

ECHO_STDERR = """OpenAI Codex v0.148.0
workdir: /x
--------
user
{prompt}
hook: SessionStart
ERROR: connection reset by peer"""


def test_prompt_chua_chu_quota_KHONG_bi_xep_nham_quota_capped():
    """Ca thật: nhờ review docs/BUGS.md — file đó chứa 'hit your usage limit' 4 lần."""
    prompt = "Review mục này:\nERROR: You've hit your usage limit. Upgrade to Pro"
    stderr = ECHO_STDERR.format(prompt=prompt)
    assert is_quota_error(stderr, 1)                       # thô: dính bẫy
    r = _classify_completed("codex", "gpt-5.5", _res(stderr=stderr), prompt=prompt)
    assert r.status == "error", "prompt của chính mình bị đọc thành lỗi vendor"
    assert r.reason == "vendor_exit_nonzero"
    assert any("connection reset" in w for w in r.warnings)


def test_quota_that_van_bat_duoc_du_prompt_cung_co_cum_do():
    """Chỉ bỏ phần echo, KHÔNG bỏ dòng lỗi thật của vendor ở cuối."""
    prompt = "Review: You've hit your usage limit"
    stderr = ECHO_STDERR.format(prompt=prompt).replace(
        "ERROR: connection reset by peer",
        "ERROR: You've hit your usage limit. try again at Aug 21st")
    r = _classify_completed("codex", "gpt-5.5", _res(stderr=stderr), prompt=prompt)
    assert r.status == "skipped" and r.reason == "quota_capped"


def test_strip_khong_xoa_gi_khi_khong_lien_khoi():
    """Không tìm thấy khối liền thì giữ nguyên — thà giữ thừa còn hơn xoá nhầm lỗi."""
    assert strip_echoed_prompt("a\nb\nc", "x\ny") == "a\nb\nc"
    assert strip_echoed_prompt("a\nb\nc", None) == "a\nb\nc"


def test_returncode_402_van_la_quota_du_stderr_rong():
    r = _classify_completed("grok", "auto", _res(returncode=402, stderr=""))
    assert r.status == "skipped" and r.reason == "quota_capped"


def test_loi_co_gan_giong_quota_KHONG_thanh_skipped():
    r = _classify_completed("codex", "auto",
                            _res(stderr="ERROR: unknown flag --limit-usage"))
    assert r.status == "error" and r.reason == "vendor_exit_nonzero"
