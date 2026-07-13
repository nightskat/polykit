"""P3 ToS boundary — bằng chứng dispatch KHÔNG BAO GIỜ sinh Claude full-worker.
Khóa CHÍNH XÁC mọi cặp cờ bounded để builder yếu đi là test đỏ ngay."""
from lib.dispatch_core import build_claude_cmd

TEST_MODELS = ["auto", "claude-3-5-sonnet", "claude-3-opus", "claude-3-haiku", "custom-model"]

# Cặp (flag, value) BẮT BUỘC có mặt với mọi model — thiếu 1 cái = boundary yếu.
REQUIRED_PAIRS = [
    ("--effort", "low"),
    ("--tools", ""),
    ("--permission-mode", "plan"),
]
# Cờ đứng-một-mình bắt buộc.
REQUIRED_FLAGS = ["--no-session-persistence", "--disable-slash-commands"]
# Không bao giờ được xuất hiện (dấu hiệu full-worker).
FORBIDDEN = [
    "--dangerously-skip-permissions", "acceptEdits", "bypassPermissions",
    "--permission-mode=acceptEdits", "--allowedTools", "--add-dir",
]


def _pairs(cmd):
    return list(zip(cmd, cmd[1:]))


def test_claude_cmd_always_bounded_all_flags():
    for model in TEST_MODELS:
        cmd = build_claude_cmd(model, "prompt bất kỳ")
        pairs = _pairs(cmd)
        for flag, val in REQUIRED_PAIRS:
            assert (flag, val) in pairs, f"[{model}] thiếu cặp {flag} {val!r}"
        for flag in REQUIRED_FLAGS:
            assert flag in cmd, f"[{model}] thiếu {flag}"
        for bad in FORBIDDEN:
            assert bad not in cmd, f"[{model}] xuất hiện cờ cấm {bad}"
        # permission-mode CHỈ được là plan (không có --permission-mode thứ 2 giá trị khác)
        for f, v in pairs:
            if f == "--permission-mode":
                assert v == "plan"
            if f == "--tools":
                assert v == ""


def test_run_vendor_claude_routes_through_bounded_builder():
    """Mọi model đi qua run_vendor('claude') đều nhận cmd bounded — chặn đường
    vòng nào đó gọi claude không qua build_claude_cmd."""
    import sys, subprocess
    from lib.states import VendorProbe
    from lib.dispatcher import run_vendor

    captured = {}

    class FakeCompleted:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_runner(cmd, **kw):
        captured["cmd"] = cmd
        return FakeCompleted()

    ready = lambda spec: VendorProbe(name=spec.name, path="/bin/claude", authed=True, quota_capped=False)

    for model in TEST_MODELS:
        captured.clear()
        run_vendor("claude", "prompt", model=model, runner=fake_runner, detector=ready)
        cmd = captured["cmd"]
        pairs = _pairs(cmd)
        for flag, val in REQUIRED_PAIRS:
            assert (flag, val) in pairs, f"[{model}] run_vendor bỏ cặp {flag} {val!r}"
        for flag in REQUIRED_FLAGS:
            assert flag in cmd
        for bad in FORBIDDEN:
            assert bad not in cmd
