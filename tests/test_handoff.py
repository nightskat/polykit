import pytest
from pathlib import Path
from bin.lib.handoff import build_handoff_note, write_handoff

def test_build_handoff_note():
    now_str = "2026-07-13 21:00:00"
    note = build_handoff_note(
        task="Build M3 Quota Failover",
        done=["Write quota.py", "Write notifier.py"],
        remaining=["Write tests", "Verify all passes"],
        files=["bin/lib/quota.py", "bin/lib/notifier.py"],
        now=now_str
    )
    
    assert now_str in note
    assert "# Handoff — 2026-07-13 21:00:00" in note
    assert "## Task" in note
    assert "Build M3 Quota Failover" in note
    assert "## Đã làm" in note
    assert "- Write quota.py" in note
    assert "- Write notifier.py" in note
    assert "## Còn lại" in note
    assert "- Write tests" in note
    assert "- Verify all passes" in note
    assert "## Files liên quan" in note
    assert "- bin/lib/quota.py" in note
    assert "- bin/lib/notifier.py" in note
    assert "## Cách tiếp" in note

def test_build_handoff_note_empty():
    now_str = "2026-07-13 21:00:00"
    note = build_handoff_note(
        task="Build M3 Quota Failover",
        done=[],
        remaining=[],
        files=[],
        now=now_str
    )
    
    assert "(chưa có)" in note
    assert "## Đã làm\n- (chưa có)" in note
    assert "## Còn lại\n- (chưa có)" in note
    assert "## Files liên quan\n- (chưa có)" in note

def test_write_handoff(tmp_path):
    note = "Test note contents"
    target_file = tmp_path / "test-handoff.md"
    written_path = write_handoff(note, path=target_file)
    
    assert written_path.exists()
    assert written_path.read_text(encoding="utf-8") == note
