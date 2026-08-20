"""BUG-6: cờ --stream-diagnose cho dispatch — chạy vendor ở chế độ stream để khi
timeout còn đọc được vendor đã đi tới đâu.

Đo thật 20/08 (docs/BUGS.md): vendor chế độ mặc định chỉ in MỘT LẦN ở cuối nên
bị giết giữa chừng là stdout 0 byte. Grok `--output-format streaming-json` bị
giết sau 20s vẫn ra 4790 byte (42 thought) — bằng chứng vendor ĐANG NGHĨ.

Bộ test này bao:
  - mỗi vendor sinh đúng cờ stream;
  - vendor không hỗ trợ (dsh/claude/openrouter) có cảnh báo RÕ rồi chạy thường;
  - JSONL dở dang ở dòng cuối không nổ;
  - trích được chữ trợ lý (thành công và timeout);
  - KHÔNG có cờ thì lệnh y hệt như cũ.
"""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from lib.dispatch_core import (
    build_agy_cmd,
    build_codex_cmd,
    build_grok_cmd,
    extract_stream_text,
)
from lib.dispatcher import run_vendor
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


def _ok_runner(stdout, calls=None):
    def _run(cmd, **kwargs):
        if calls is not None:
            calls.append(cmd)
        m = MagicMock()
        m.returncode = 0
        m.stdout = stdout
        m.stderr = ""
        return m
    return _run


# ── 1. Cờ stream đúng cho từng vendor (build_*_cmd) ─────────────────────────

def test_build_codex_cmd_stream_them_co_json():
    cmd = build_codex_cmd("auto", "read-only", None, "text", stream=True)
    assert "--json" in cmd


def test_build_grok_cmd_stream_dung_streaming_json():
    grok_bin = str(Path.home() / ".grok/bin/grok")
    cmd = build_grok_cmd("auto", "read-only", None, "text", "/tmp/p", stream=True)
    assert ["--output-format", "streaming-json"] in [cmd[i:i+2] for i in range(len(cmd))]


def test_build_agy_cmd_stream_dat_truoc_lenh_con():
    cmd = build_agy_cmd("gemini-3.6-flash-high", "prompt", stream=True)
    assert cmd == [
        "agy", "--output-format", "stream-json",
        "--model", "gemini-3.6-flash-high", "-p", "prompt",
    ]
    # Cờ TOÀN CỤC phải đứng TRƯỚC lệnh con -p (trap: agy models --output-format json -> exit 1)
    assert cmd.index("--output-format") < cmd.index("-p")


def test_build_agy_cmd_stream_giu_nguyen_khi_khong_co():
    assert build_agy_cmd("gpt-oss-120b-medium", "p") == [
        "agy", "--model", "gpt-oss-120b-medium", "-p", "p",
    ]


# ── 2. KHÔNG có cờ thì lệnh y hệt như cũ ─────────────────────────────────────

def test_khong_co_co_codex_giong_het_cu():
    """"Giống hệt cũ" = không có cờ stream. Effort `low` là mặc định MỚI của
    PolyKit từ bench 20/08, có ở cả hai nhánh nên không phải khác biệt do stream."""
    assert build_codex_cmd("auto", "read-only", None, "text") == [
        "codex", "exec", "-c", "model_reasoning_effort=low",
        "-s", "read-only", "--skip-git-repo-check",
    ]
    assert build_codex_cmd("gpt-4", "workspace-write", "/p", "json") == [
        "codex", "exec", "-m", "gpt-4", "-c", "model_reasoning_effort=low",
        "-s", "workspace-write", "--json", "-C", "/p", "--skip-git-repo-check",
    ]


def test_khong_co_co_grok_giong_het_cu():
    grok_bin = str(Path.home() / ".grok/bin/grok")
    assert build_grok_cmd("auto", "read-only", None, "text", "/tmp/p") == [
        grok_bin, "--prompt-file", "/tmp/p",
        "--tools", "read_file,grep,list_dir", "--always-approve",
    ]


def test_run_vendor_khong_co_co_khong_canh_bao_che_do_chan_doan():
    r = run_vendor("codex", "xin chao", runner=_ok_runner("OK"), detector=_ready_detector)
    assert r.status == "ok"
    assert not any("chẩn đoán" in w or "KHÔNG áp dụng" in w for w in r.warnings)


# ── 3. Vendor KHÔNG hỗ trợ stream → cảnh báo rõ, chạy bình thường ────────────

def test_dsh_stream_canh_bao_ro_va_chay_binh_thuong():
    calls = []
    r = run_vendor("dsh", "hi", stream=True,
                   runner=_ok_runner("done", calls), detector=_ready_detector)
    assert r.status == "ok"
    assert r.stdout == "done"
    # Không giả vờ stream: lệnh không hề có cờ stream nào.
    assert not any("--output-format" in a for a in calls[0])
    assert any("KHÔNG áp dụng" in w and "dsh" in w for w in r.warnings)


def test_claude_stream_canh_bao_ro():
    calls = []
    r = run_vendor("claude", "hi", stream=True,
                   runner=_ok_runner("ok", calls), detector=_ready_detector)
    assert r.status == "ok"
    assert not any("--json" in a for a in calls[0])
    assert any("KHÔNG áp dụng" in w and "claude" in w for w in r.warnings)


def test_openrouter_stream_canh_bao_ro():
    # openrouter là HTTP API, không có CLI stream — không được bảo "JSONL stream".
    with patch("lib.openrouter.or_dispatch") as or_dispatch:
        class _R:
            ok = True
            served_model = "openai/gpt-oss"
            text = "ket qua"
        or_dispatch.return_value = _R()
        r = run_vendor("openrouter", "hi", stream=True)
    assert any("KHÔNG áp dụng" in w and "openrouter" in w for w in r.warnings)


# ── 4. extract_stream_text: trích chữ trợ lý, chịu dòng JSON dở dang ─────────

def test_trich_duoc_chu_tro_ly_grok_thought():
    raw = ('{"type":"thought","text":"vendor dang nghi ve X"}\n'
           '{"type":"assistant","text":"ket qua day"}\n')
    text = extract_stream_text(raw)
    assert "vendor dang nghi ve X" in text
    assert "ket qua day" in text


def test_trich_duoc_chu_tro_ly_codex_assistant_message():
    raw = ('{"type":"assistant_message","message":{"role":"assistant",'
           '"content":[{"type":"output_text","text":"xin chao"}]}}')
    assert extract_stream_text(raw) == "xin chao"


def test_dong_json_do_dang_o_cuoi_khong_no():
    # Dòng cuối bị cắt giữa chừng (bị giết lúc đang ghi) → bỏ qua, không nổ.
    raw = ('{"type":"thought","text":"dong hop le"}\n'
           '{"type":"thought","text":"dong bi cat giua chung')
    assert extract_stream_text(raw) == "dong hop le"


def test_khong_trich_duoc_tra_rong_de_caller_giu_tho():
    assert extract_stream_text('{"type":"available_commands"}\n'
                               '{"type":"session_started"}') == ""
    assert extract_stream_text("") == ""
    assert extract_stream_text("day khong phai json") == ""


# ── 5. Stream THÀNH CÔNG: stdout thành chữ trợ lý, không mất dữ liệu ─────────

def test_codex_stream_thanh_cong_trich_chu_tro_ly():
    calls = []
    r = run_vendor("codex", "hi", stream=True,
                   runner=_ok_runner('{"type":"text","text":"OK"}', calls),
                   detector=_ready_detector)
    assert "--json" in calls[0]
    assert r.status == "ok"
    assert r.stdout == "OK"  # đã trích phần chữ, không còn JSONL thô
    assert any("chẩn đoán" in w for w in r.warnings)


def test_gemini_stream_them_co_o_stream_json():
    calls = []
    r = run_vendor("gemini", "xin chao", model="gemini-2.5-pro", stream=True,
                   runner=_ok_runner('{"type":"text","text":"OK"}', calls))
    assert r.status == "ok"
    cmd = calls[0]
    assert "-o" in cmd and "stream-json" in cmd
    assert r.stdout == "OK"


# ── 6. Stream TIMEOUT: đọc được vendor đã đi tới đâu ─────────────────────────

def test_stream_timeout_trich_duoc_thought():
    jsonl = ('{"type":"thought","text":"vendor dang nghi ve X"}\n'
             '{"type":"thought","text":"dang phan tich file"}\n')

    def mock_runner(cmd, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd, kwargs.get("timeout", 120), output=jsonl, stderr="",
        )

    r = run_vendor("grok", "review", stream=True,
                   runner=mock_runner, detector=_ready_detector)
    assert r.status == "timeout"
    assert r.stdout == ""  # hợp đồng cũ: timeout thì stdout vẫn rỗng
    assert any("trích từ JSONL stream" in w for w in r.warnings)
    assert any("vendor dang nghi ve X" in w for w in r.warnings)
    assert any("dang phan tich file" in w for w in r.warnings)


def test_stream_timeout_khong_trich_duoc_van_giu_tho():
    def mock_runner(cmd, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd, kwargs.get("timeout", 120),
            output='{"type":"available_commands"}\n', stderr="",
        )

    r = run_vendor("grok", "review", stream=True,
                   runner=mock_runner, detector=_ready_detector)
    assert r.status == "timeout"
    assert any("không trích được chữ" in w for w in r.warnings)


# ── ba lỗ Codex review chỉ ra (20/08) ───────────────────────────────────────

from lib.dispatch_core import extract_stream_text as _ext
from lib.dispatcher import STREAM_UNSUPPORTED, _apply_stream_diagnose
from lib.dispatch_core import DispatchResult as _DR


def test_khong_trich_nham_log_loi_ha_tang_thanh_chu_tro_ly():
    """Đo thật: codex --json phát item.completed bọc một item type=error."""
    raw = (
        '{"type":"item.completed","item":{"id":"i0","type":"error",'
        '"message":"clamping SessionEnd hook timeout"}}\n'
        '{"type":"item.completed","item":{"type":"assistant_message",'
        '"text":"Đây mới là chữ trợ lý"}}\n'
    )
    out = _ext(raw)
    assert "Đây mới là chữ trợ lý" in out
    assert "clamping" not in out, "log lỗi hạ tầng bị trích thành chữ trợ lý"


def test_khong_trich_nham_luot_cua_nguoi_dung():
    raw = '{"role":"user","content":"prompt của tôi"}\n{"role":"assistant","content":"trả lời"}\n'
    out = _ext(raw)
    assert "trả lời" in out and "prompt của tôi" not in out


def test_format_json_thi_GIU_NGUYEN_jsonl_tho():
    """Caller xin --format json là đang cần JSON; thay bằng chữ trích là phá hợp đồng."""
    raw = '{"type":"item.completed","item":{"type":"assistant_message","text":"xin chào"}}'
    r = _DR(status="ok", vendor="codex", model="auto", summary="", stdout=raw, exit_code=0)
    out = _apply_stream_diagnose(r, "codex", stream=True, fmt="json")
    assert out.stdout == raw
    assert any("giữ nguyên JSONL thô" in w for w in out.warnings)


def test_lane1_agy_phai_noi_that_la_khong_stream():
    """Lane 2 (gemini-cli) CÓ stream nên gemini không bị xếp 'không hỗ trợ'.
    Nhưng lane 1 (agy) thì không — im lặng ở đó là để ghi chú chung nói hộ."""
    assert "gemini" not in STREAM_UNSUPPORTED
    calls = []
    r = run_vendor("gemini", "xin chao", model="gemini-3.6-flash-medium", stream=True,
                   runner=_ok_runner("xong", calls))
    assert any("lane 1 (agy) KHÔNG nhận cờ stream" in w for w in r.warnings), r.warnings
