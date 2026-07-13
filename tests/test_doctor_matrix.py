import pytest
from lib.states import VendorProbe
from lib.state_store import build_state
from doctor import render_table


def _vendor_line_block(table_str, name):
    """Trả về dòng vendor + các dòng hint ngay dưới nó (đến vendor kế tiếp)."""
    lines = table_str.splitlines()
    others = {"codex", "gemini", "claude", "grok"} - {name}
    out, capture = [], False
    for ln in lines:
        head = ln.split("|", 1)[0].strip()
        if head == name:
            capture = True
            out.append(ln)
            continue
        if capture and head in others:
            break
        if capture:
            out.append(ln)
    return "\n".join(out)

@pytest.mark.parametrize(
    "combo_name, probes, expected_states, expected_hints",
    [
        (
            "0_vendor",
            [
                VendorProbe("codex", None, False, False),
                VendorProbe("gemini", None, False, False),
                VendorProbe("claude", None, False, False),
                VendorProbe("grok", None, False, False),
            ],
            {
                "codex": "not_installed",
                "gemini": "not_installed",
                "claude": "not_installed",
                "grok": "not_installed",
            },
            ["chạy `codex login`", "chạy `gemini` rồi /auth", "đã auth qua Claude Code", "chạy `grok` để auth"]
        ),
        (
            "claude_only",
            [
                VendorProbe("codex", None, False, False),
                VendorProbe("gemini", None, False, False),
                VendorProbe("claude", "/usr/bin/claude", True, False, "2.1.207"),
                VendorProbe("grok", None, False, False),
            ],
            {
                "codex": "not_installed",
                "gemini": "not_installed",
                "claude": "ready",
                "grok": "not_installed",
            },
            ["chạy `codex login`", "chạy `gemini` rồi /auth", "chạy `grok` để auth"]
        ),
        (
            "codex_only",
            [
                VendorProbe("codex", "/usr/bin/codex", True, False, "0.144.2"),
                VendorProbe("gemini", None, False, False),
                VendorProbe("claude", None, False, False),
                VendorProbe("grok", None, False, False),
            ],
            {
                "codex": "ready",
                "gemini": "not_installed",
                "claude": "not_installed",
                "grok": "not_installed",
            },
            ["chạy `gemini` rồi /auth", "đã auth qua Claude Code", "chạy `grok` để auth"]
        ),
        (
            "gemini_only",
            [
                VendorProbe("codex", None, False, False),
                VendorProbe("gemini", "/usr/bin/gemini", True, False, "0.50.0"),
                VendorProbe("claude", None, False, False),
                VendorProbe("grok", None, False, False),
            ],
            {
                "codex": "not_installed",
                "gemini": "ready",
                "claude": "not_installed",
                "grok": "not_installed",
            },
            ["chạy `codex login`", "đã auth qua Claude Code", "chạy `grok` để auth"]
        ),
        (
            "has_not_authed",
            [
                VendorProbe("codex", "/usr/bin/codex", False, False, "0.144.2"),
                VendorProbe("gemini", None, False, False),
                VendorProbe("claude", None, False, False),
                VendorProbe("grok", None, False, False),
            ],
            {
                "codex": "installed_not_authed",
                "gemini": "not_installed",
                "claude": "not_installed",
                "grok": "not_installed",
            },
            ["chạy `codex login`", "chạy `gemini` rồi /auth", "đã auth qua Claude Code", "chạy `grok` để auth"]
        ),
    ]
)
def test_doctor_matrix(combo_name, probes, expected_states, expected_hints):
    now_str = "2026-07-13T19:39:10+07:00"
    state = build_state(probes, now_str)

    assert state["schema_version"] == 1
    assert state["generated_at"] == now_str

    for name, expected_state in expected_states.items():
        assert name in state["vendors"]
        assert state["vendors"][name]["state"] == expected_state

    table_str = render_table(state)
    from lib.vendors import REGISTRY

    # Combo 0-vendor vẫn in đủ 4 dòng, không raise.
    for name in ["codex", "gemini", "claude", "grok"]:
        assert name in table_str

    # Hint đúng theo state, kiểm THEO KHỐI DÒNG của từng vendor (tránh false-positive substring).
    for name, expected_state in expected_states.items():
        block = _vendor_line_block(table_str, name)
        hint = REGISTRY[name].auth_hint
        if expected_state == "installed_not_authed":
            assert hint in block  # chỉ not_authed mới hiện auth hint
        elif expected_state == "not_installed":
            assert "Chưa cài" in block and hint not in block
        elif expected_state == "ready":
            assert hint not in block  # ready không có dòng hint
