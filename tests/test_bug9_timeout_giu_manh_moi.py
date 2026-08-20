"""BUG-9: timeout phải GIỮ manh mối vendor đã in ra TRƯỚC khi bị giết.

Trước đây nhánh `except subprocess.TimeoutExpired` trả DispatchResult với
warnings=[] và không đặt stdout — vứt sạch e.stdout/e.stderr. BUG-6 đang bí vì
lý do này: grok/dsh cùng timeout với stdout rỗng, không ai biết vendor đã làm
tới đâu.

Bản vá: decode None/str/bytes → str, bỏ echo prompt bằng strip_echoed_prompt,
cắt đuôi bằng tail_lines, và phân biệt rõ `[polykit]` (ghi chú) với
`[vendor:stdout|stderr]` (output DANG DỞ). status/reason giữ nguyên timeout.
"""
import subprocess

from lib.dispatcher import (
    STDERR_HEAD,
    STDERR_KEEP,
    _decode_partial,
    run_vendor,
)
from lib.states import VendorProbe


def _ready_detector(spec):
    return VendorProbe(
        name=spec.name,
        path=f"/fake/{spec.name}",
        authed=True,
        quota_capped=False,
        version="1.0",
        models=[],
        error=None,
    )


def _runner_raising(stdout, stderr):
    def _run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd, kwargs.get("timeout", 120), output=stdout, stderr=stderr
        )

    return _run


def _run_timeout(stdout, stderr, prompt="inventory nhanh"):
    return run_vendor(
        "claude",
        prompt,
        runner=_runner_raising(stdout, stderr),
        detector=_ready_detector,
    )


# ── 1. decode ba kiểu None/str/bytes về str, không để nổ ────────────────────

def test_decode_partial_none_str_bytes():
    assert _decode_partial(None) == ""
    assert _decode_partial("chữ") == "chữ"
    assert _decode_partial(b"bytes \xe2\x9c\x93") == "bytes \u2713"


def test_decode_partial_bytes_hong_utf8_van_khong_no():
    # bytes có byte không hợp lệ UTF-8 → decode với errors=replace, không nổ.
    assert _decode_partial(b"\xff\xfe\x80") == "\ufffd\ufffd\ufffd"


# ── 2. e.stdout/e.stderr là bytes: giữ lại, không vứt ───────────────────────

def test_timeout_giau_manh_moi_khi_ca_hai_la_bytes():
    r = _run_timeout(b"phan tich xong 1 nua", b"warn: cham")
    assert r.status == "timeout"
    assert r.reason == "timeout"
    # stdout PHẢI rỗng: trường này là "kết quả vendor". Nhét output dang dở vào
    # đây thì caller chỉ kiểm `stdout != ""` sẽ đọc nửa vời thành kết quả thật
    # (Codex review 20/08). Manh mối nằm trong warnings, đã qua tail_lines.
    assert r.stdout == ""
    assert any("DANG DỞ" in w and "STDOUT" in w for w in r.warnings)
    assert any("[vendor:stdout] phan tich xong 1 nua" in w for w in r.warnings)
    assert any("[vendor:stderr] warn: cham" in w for w in r.warnings)


# ── 3. e.stdout/e.stderr là None: phải nói rõ "không kịp in gì", không im lặng

def test_timeout_khi_none_phai_noi_ro_khong_in_gi():
    r = _run_timeout(None, None)
    assert r.status == "timeout"
    assert r.reason == "timeout"
    assert r.stdout == ""
    assert r.warnings, "warnings không được rỗng im lặng"
    assert any("KHÔNG kịp in gì ra stdout" in w for w in r.warnings)
    assert any("KHÔNG kịp in gì ra stderr" in w for w in r.warnings)


# ── 4. echo prompt bị bỏ, không đọc lại chữ của chính mình ──────────────────

def test_timeout_bo_echo_prompt_khoi_stderr():
    prompt = "review docs/BUGS.md"
    stderr = f"banner\n{prompt}\nERROR: connection reset by peer"
    r = _run_timeout("", stderr, prompt=prompt)
    assert all(prompt not in w for w in r.warnings), r.warnings
    assert any("[vendor:stderr] ERROR: connection reset by peer" in w
               for w in r.warnings)
    # stdout rỗng → vẫn phải có ghi chú riêng cho kênh stdout.
    assert any("KHÔNG kịp in gì ra stdout" in w for w in r.warnings)


# ── 5. stderr dài: cắt đúng kiểu tail_lines (đầu + đuôi, ghi rõ bỏ bao nhiêu)

def test_timeout_stderr_dai_cat_dung_kieu_tail_lines():
    stderr = "\n".join(
        [f"banner {i}" for i in range(50)] + ["ERROR: loi thuc o cuoi"]
    )
    r = _run_timeout("", stderr)
    tagged = [w for w in r.warnings if w.startswith("[vendor:stderr]")]
    # tail_lines giữ `head` dòng đầu + `keep` dòng cuối; dòng ghi chú cắt là của
    # PolyKit nên KHÔNG được gắn nhãn vendor.
    assert len(tagged) == STDERR_HEAD + STDERR_KEEP
    assert any("loi thuc o cuoi" in w for w in tagged)
    assert any("banner 0" in w for w in tagged)
    assert any(w.startswith("[polykit]") and "bỏ" in w for w in r.warnings)


# ── 6. hợp đồng JSON giữ nguyên: status/reason không đổi ────────────────────

def test_timeout_van_giu_nguyen_status_va_reason():
    r = _run_timeout("mot phan", "loi mot phan")
    assert r.status == "timeout"
    assert r.reason == "timeout"
    d = r.to_dict()
    assert d["status"] == "timeout"
    assert d["reason"] == "timeout"
    assert isinstance(d["warnings"], list)


# ── 6. ba lỗ Codex review chỉ ra (20/08) ────────────────────────────────────

def test_stdout_luon_rong_khi_timeout_du_vendor_in_rat_nhieu():
    """Không để JSON phình vô hạn, và không để caller nhầm là kết quả thật."""
    r = _run_timeout("x" * 500_000, "")
    assert r.stdout == ""
    assert len(r.warnings) <= STDERR_HEAD + STDERR_KEEP + 4


def test_stderr_chi_co_echo_prompt_thi_noi_ro_la_da_bo_echo():
    """Khác hẳn 'vendor im lặng' — hai ca dẫn tới hai hướng chẩn đoán khác nhau."""
    prompt = "dòng một\ndòng hai"
    r = _run_timeout("", "dòng một\ndòng hai", prompt=prompt)
    assert any("chỉ có phần echo lại prompt" in w for w in r.warnings)
    assert not any("KHÔNG kịp in gì ra stderr" in w for w in r.warnings)


def test_decode_partial_kieu_la_khong_no():
    class La:
        def __str__(self): return "đối tượng lạ"
    assert _decode_partial(La()) == "đối tượng lạ"
