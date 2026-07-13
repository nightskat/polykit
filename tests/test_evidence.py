import pytest
from pathlib import Path
from bin.lib.evidence import append_evidence, read_evidence, make_record

def test_append_and_read_evidence(tmp_path):
    log_file = tmp_path / "test_log.jsonl"
    record1 = make_record("grok", "grok-2", "success", "2026-07-13T22:00:00Z", None, 150)
    record2 = make_record("grok", "grok-2", "quota_capped", "2026-07-13T22:01:00Z", "out of credit", None)
    
    assert append_evidence(record1, path=log_file) is True
    assert append_evidence(record2, path=log_file) is True
    
    records = read_evidence(limit=10, path=log_file)
    assert len(records) == 2
    assert records[0] == record1
    assert records[1] == record2

def test_append_evidence_error_returns_false(tmp_path):
    # Path is a directory, writing to it should fail
    dir_path = tmp_path / "invalid_path"
    dir_path.mkdir()
    
    record = make_record("grok", "grok-2", "success", "2026-07-13T22:00:00Z")
    assert append_evidence(record, path=dir_path) is False

def test_make_record_fields():
    record = make_record(
        vendor="grok",
        model="grok-2",
        status="quota_capped",
        now="2026-07-13T22:00:00Z",
        reason=None,
        latency_ms=None
    )
    assert record == {
        "ts": "2026-07-13T22:00:00Z",
        "vendor": "grok",
        "model": "grok-2",
        "status": "quota_capped",
        "reason": None,
        "latency_ms": None
    }

def test_read_evidence_missing_file(tmp_path):
    non_existent = tmp_path / "does_not_exist.jsonl"
    assert read_evidence(limit=20, path=non_existent) == []

def test_read_evidence_limit(tmp_path):
    log_file = tmp_path / "limit_test.jsonl"
    for i in range(5):
        record = make_record("grok", f"grok-{i}", "success", f"2026-07-13T22:0{i}:00Z")
        append_evidence(record, path=log_file)
    
    records = read_evidence(limit=3, path=log_file)
    assert len(records) == 3
    assert records[0]["model"] == "grok-2"
    assert records[1]["model"] == "grok-3"
    assert records[2]["model"] == "grok-4"
