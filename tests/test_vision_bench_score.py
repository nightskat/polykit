"""Unit and integration tests for synthetic vision benchmark scorer and runner.

Verifies:
  1. Typed parsing:
     - Amount: Decimal comparison, VN dot thousands, parentheses negative,
       no permissive stripping of letters, no booleans, no NaN/inf, sign mismatch.
     - Date: ISO and VN dd/mm/yyyy parsing, invalid calendar dates, year confusion (2026 vs 2006).
     - Code: Exact string comparison, 0 vs O, 1 vs l, case sensitivity.
     - Text: Unicode NFC normalization, whitespace normalization, case sensitivity.
  2. JSON Parser:
     - opencode --format json JSONL event stream text
     - Markdown fenced JSON (```json ... ```)
     - Outermost JSON extraction with conversational preamble/postscript
     - Corrupted or invalid JSON handling
  3. Scorer evaluation:
     - Missing fields counted as wrong (not excluded from total)
     - Strict field ID mapping (never use truth to fill predictions)
     - Grouped statistics by document and by type
  4. Baseline vnocr token recovery:
     - Page marker splitting (===== page_...png ...)
     - Strict token recovery (no fuzzy matching, wrong digit fails, 0/O misread fails)
     - Upper-bound recovery metric labeling and disclaimer
  5. Runner prompt builder and security:
     - Strictly no 'value' or 'numeric_value' in prompts
     - Answer leak scrubbing in field names
     - Overwrite guarding and argv safety
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import tempfile
import unicodedata
import pytest

from bench.vision.score import (
    compare_field,
    detect_tool_events,
    extract_stream_text_from_jsonl,
    parse_amount,
    parse_code,
    parse_date,
    parse_json_response,
    parse_text,
    score_ocr_text_recovery,
    score_predictions,
    split_ocr_pages,
    strict_json_loads,
)
from bench.vision.run import (
    build_prompt_for_fields,
    execute_benchmark,
    run_dispatch_call,
    sanitize_field_name,
)
import bench.vision.run as run_mod


# ---------------------------------------------------------------------------
# 1. Typed Amount Parsing Tests
# ---------------------------------------------------------------------------

def test_amount_vn_dot_thousands() -> None:
    """VN dot thousands must be parsed to exact Decimal."""
    assert parse_amount("1.234.567.890") == Decimal("1234567890")
    assert parse_amount("890.123.456") == Decimal("890123456")
    assert parse_amount("450.000.000") == Decimal("450000000")
    assert parse_amount("1.234.567,50") == Decimal("1234567.50")


def test_amount_parentheses_and_sign_negative() -> None:
    """Accounting parentheses (12.345) and minus signs must parse as negative Decimal."""
    assert parse_amount("(12.345)") == Decimal("-12345")
    assert parse_amount("(98.765.432)") == Decimal("-98765432")
    assert parse_amount("-12.345") == Decimal("-12345")
    assert parse_amount("-(12.345)") == Decimal("-12345") or parse_amount("-12345") == Decimal("-12345")
    assert parse_amount("( 15.500.000 )") == Decimal("-15500000")

    # Sign mismatch between positive and negative
    assert parse_amount("12.345") != parse_amount("(12.345)")


def test_amount_trailing_currency_unit_whitelist() -> None:
    """Exactly 'VND'/'VNĐ'/'đ' as a single trailing unit must compare by NUMERIC VALUE.

    The brief asks for numeric correctness: a model answering the right number
    with a currency suffix is not a wrong amount.
    """
    assert parse_amount("56.810.000 VND") == Decimal("56810000")
    assert parse_amount("56.810.000 VNĐ") == Decimal("56810000")
    assert parse_amount("56.810.000 đ") == Decimal("56810000")
    assert parse_amount("(12.345) VNĐ") == Decimal("-12345")

    # casefold + whitespace variants
    assert parse_amount("56.810.000 vnd") == Decimal("56810000")
    assert parse_amount("56.810.000 Vnđ") == Decimal("56810000")
    assert parse_amount("56.810.000 Đ") == Decimal("56810000")
    assert parse_amount("56.810.000   VND") == Decimal("56810000")
    assert parse_amount("56810000\tVND") == Decimal("56810000")
    assert parse_amount("56 810 000 VND") == Decimal("56810000")

    # Suffix must not change the sign or the decimals
    assert parse_amount("-12.345 đ") == Decimal("-12345")
    assert parse_amount("1.234.567,50 VND") == Decimal("1234567.50")
    assert parse_amount("56.810.000 VND") != parse_amount("-56.810.000 VND")


def test_amount_currency_suffix_rejections() -> None:
    """Only the whitelisted trailing unit is tolerated; nothing else is stripped."""
    # Letters glued to digits / prefix units / units in the middle
    assert parse_amount("123abc") is None
    assert parse_amount("VND123") is None
    assert parse_amount("VND 12345") is None
    assert parse_amount("12345VND") is None
    assert parse_amount("123 VND xyz") is None
    assert parse_amount("12345 VN") is None
    # Other currencies are NOT whitelisted
    assert parse_amount("123 USD") is None
    assert parse_amount("123 EUR") is None
    assert parse_amount("123 usd") is None
    # Multiple amounts / repeated units
    assert parse_amount("123 VND 456") is None
    assert parse_amount("123 vnd vnd") is None
    assert parse_amount("12345 67890") is None
    assert parse_amount("1 2 3") is None
    # Bare units, conflicting signs
    assert parse_amount("VND") is None
    assert parse_amount("đ") is None
    assert parse_amount("-(12.345)") is None
    assert parse_amount("(-12.345)") is None
    assert parse_amount("12.345đ") is None


def test_amount_currency_suffix_scores_as_correct_value() -> None:
    """A right number carrying 'VND' must be counted correct, not a format error."""
    correct, parsed_gt, parsed_pred, reason = compare_field(
        "amount", "56.810.000", "56.810.000 VND"
    )
    assert correct is True
    assert parsed_gt == "56810000"
    assert parsed_pred == "56810000"
    assert reason is None

    # Suffixed but numerically different must still fail as amount_mismatch
    correct, _, _, reason = compare_field("amount", "56.810.000", "56.810.001 VNĐ")
    assert correct is False
    assert reason == "amount_mismatch"

    # Unknown currency is still a format problem, not a silent match
    correct, _, _, reason = compare_field("amount", "56.810.000", "56.810.000 USD")
    assert correct is False
    assert reason == "invalid_amount_format"


def test_amount_rejections_no_letters_no_booleans_no_nan() -> None:
    """Strictly reject permissive letter stripping, booleans, and NaN."""
    # Permissive letter stripping MUST NOT occur
    assert parse_amount("12345abc") is None
    assert parse_amount("VND 12345") is None
    assert parse_amount("N/A") is None

    # Booleans are not numbers
    assert parse_amount(True) is None
    assert parse_amount(False) is None

    # NaN / Inf
    assert parse_amount("NaN") is None
    assert parse_amount("nan") is None
    assert parse_amount("Infinity") is None
    assert parse_amount("-inf") is None
    assert parse_amount(float("nan")) is None
    assert parse_amount(float("inf")) is None

    # Ambiguous separators
    assert parse_amount("1.2.3") is None
    assert parse_amount("1,,234") is None


# ---------------------------------------------------------------------------
# 2. Typed Date Parsing & Year Tests
# ---------------------------------------------------------------------------

def test_date_iso_and_vn_formats() -> None:
    """Valid ISO and VN date strings must parse to matching date objects."""
    iso_date = parse_date("2026-06-30")
    vn_date = parse_date("30/06/2026")
    dash_vn_date = parse_date("30-06-2026")

    assert iso_date == date(2026, 6, 30)
    assert vn_date == date(2026, 6, 30)
    assert iso_date == vn_date
    assert dash_vn_date == date(2026, 6, 30)


def test_date_year_confusion_and_calendar_validity() -> None:
    """Year 2026 vs 2006 confusion must fail; invalid calendar dates must be rejected."""
    d_2026 = parse_date("2026-01-15")
    d_2006 = parse_date("2006-01-15")
    assert d_2026 != d_2006

    # Invalid calendar dates
    assert parse_date("31/02/2026") is None  # Feb 31 does not exist
    assert parse_date("2026-13-01") is None  # Month 13
    assert parse_date("2026-00-10") is None  # Month 00
    assert parse_date("2026-06-30abc") is None  # Corrupted with letters
    assert parse_date(2026) is None  # Integer not accepted as valid date string


# ---------------------------------------------------------------------------
# 3. Typed Code & Text Parsing (0/O, 1/l, NFC, Case)
# ---------------------------------------------------------------------------

def test_code_exact_string_and_confusing_characters() -> None:
    """Codes must match character-for-character, distinguishing 0 vs O and 1 vs l."""
    gt_code = "HD-2026-O0l1586B"

    # Exact match passes
    assert parse_code("HD-2026-O0l1586B") == gt_code

    # 0 vs O confusion must fail
    assert parse_code("HD-2026-00l1586B") != gt_code
    assert parse_code("HD-2026-OOl1586B") != gt_code

    # 1 vs l confusion must fail
    assert parse_code("HD-2026-O011586B") != gt_code
    assert parse_code("REF-2006-0Ol1") != parse_code("REF-2006-0O11")

    # Case sensitivity must fail
    assert parse_code("hd-2026-o0l1586b") != gt_code


def test_text_unicode_nfc_and_whitespace_case_sensitive() -> None:
    """Text must normalize Unicode NFC and whitespace, but remain case-sensitive."""
    base_text = "Công ty Cổ phần Công nghệ Sao Kim"

    # Precomposed NFC vs Decomposed NFD
    nfd_text = unicodedata.normalize("NFD", base_text)
    assert parse_text(nfd_text) == base_text

    # Whitespace normalization
    messy_space = "  Công ty    Cổ phần   Công nghệ   Sao Kim \n "
    assert parse_text(messy_space) == base_text

    # Case-sensitive check
    lower_text = "công ty cổ phần công nghệ sao kim"
    assert parse_text(lower_text) != base_text


# ---------------------------------------------------------------------------
# 4. JSON Parser Tests (opencode JSONL, Markdown fenced, Corrupted)
# ---------------------------------------------------------------------------

def test_json_parser_plain_and_fenced() -> None:
    """Supports plain JSON and markdown fenced blocks."""
    plain = '{"p1_rev_q1": "1.234.567.890", "p1_period_date": "2026-06-30"}'
    assert parse_json_response(plain) == {
        "p1_rev_q1": "1.234.567.890",
        "p1_period_date": "2026-06-30",
    }

    fenced = (
        "Dưới đây là kết quả trích xuất:\n\n"
        "```json\n"
        "{\n"
        '  "p1_rev_q1": "1.234.567.890",\n'
        '  "p1_period_date": "2026-06-30"\n'
        "}\n"
        "```\n"
        "Hy vọng hữu ích!"
    )
    assert parse_json_response(fenced) == {
        "p1_rev_q1": "1.234.567.890",
        "p1_period_date": "2026-06-30",
    }


def test_json_parser_opencode_jsonl_stream() -> None:
    """Extracts JSON from opencode --format json JSONL event stream lines."""
    inner_payload = '```json\n{"p1_rev_q1": "1.234.567.890", "p1_report_code": "BCTC-2026-NARROW"}\n```'
    jsonl_output = "\n".join([
        json.dumps({"type": "init", "session": "abc"}),
        json.dumps({"type": "text", "part": {"text": inner_payload}}),
        json.dumps({"type": "done"}),
    ])
    parsed = parse_json_response(jsonl_output)
    assert parsed is not None
    assert parsed["p1_rev_q1"] == "1.234.567.890"
    assert parsed["p1_report_code"] == "BCTC-2026-NARROW"


def test_json_parser_corrupted_and_invalid() -> None:
    """Corrupted JSON, empty strings, and non-dicts must return None without crashing."""
    assert parse_json_response("") is None
    assert parse_json_response("This is just conversational text with no json") is None
    assert parse_json_response("{malformed json: broken") is None
    assert parse_json_response('["list", "not", "dict"]') is None


# ---------------------------------------------------------------------------
# 5. Scorer Accuracy & Strict Field Mapping Tests
# ---------------------------------------------------------------------------

def test_score_predictions_strict_mapping_and_missing() -> None:
    """Missing fields are counted wrong; truth is never used to backfill outputs."""
    gt_data = {
        "fields": [
            {"id": "p1_rev", "document": "page1.png", "type": "amount", "value": "1.234.567.890"},
            {"id": "p1_date", "document": "page1.png", "type": "date", "value": "2026-06-30"},
            {"id": "p1_code", "document": "page1.png", "type": "code", "value": "BCTC-2026"},
            {"id": "p1_text", "document": "page1.png", "type": "text", "value": "Công ty Sao Kim"},
        ]
    }

    # Model provides 2 correct, 1 wrong, 1 missing, plus 1 extra hallucinated field
    preds = {
        "p1_rev": "1234567890",         # Correct (Decimal equivalent)
        "p1_date": "30/06/2026",        # Correct (valid VN format of 2026-06-30)
        "p1_code": "BCTC-2006",         # Wrong (year 2006 vs 2026)
        # p1_text is completely missing
        "hallucinated_field": "123",    # Extra field should be ignored
    }

    report = score_predictions(gt_data, preds)

    assert report["total_fields"] == 4
    assert report["correct_fields"] == 2
    assert report["accuracy_percent"] == 50.0

    field_map = {f["id"]: f for f in report["fields"]}
    assert field_map["p1_rev"]["correct"] is True
    assert field_map["p1_date"]["correct"] is True
    assert field_map["p1_code"]["correct"] is False
    assert field_map["p1_code"]["error_reason"] == "code_mismatch"
    assert field_map["p1_text"]["correct"] is False
    assert field_map["p1_text"]["error_reason"] == "missing"

    # Verify grouped stats
    assert "page1.png" in report["by_document"]
    assert report["by_document"]["page1.png"]["correct"] == 2
    assert report["by_document"]["page1.png"]["total"] == 4

    assert report["by_type"]["amount"]["correct"] == 1
    assert report["by_type"]["code"]["correct"] == 0
    assert report["by_type"]["text"]["correct"] == 0


# ---------------------------------------------------------------------------
# 6. Baseline vnocr Token Recovery Tests
# ---------------------------------------------------------------------------

def test_baseline_ocr_recovery_strict_no_fuzzy() -> None:
    """OCR token recovery must be exact per type; wrong digits and 0/O errors must fail."""
    sample_ocr = (
        "===== page_01_narrow_table.png 500 ký tự [tin cậy=0.99]\n"
        "BÁO CÁO LƯU CHUYỂN TIỀN TỆ\n"
        "Doanh thu: 1.234.567.890\n"
        "Giá vốn: 890.123.156\n"  # Wrong digit: 156 instead of 456
        "Mã: BCTC-2026-NARROW\n"
        "\n"
        "===== page_03_confusing_chars.png 400 ký tự [tin cậy=0.99]\n"
        "Mã hợp đồng: HC-2028-0011586B\n"  # Misread D->C, 2026->2028, O->0, l->1
        "Ngày: 15/01/2026\n"
    )

    gt_data = {
        "fields": [
            # p1_rev matches exact candidate
            {"id": "p1_rev", "document": "page_01_narrow_table.png", "type": "amount", "value": "1.234.567.890"},
            # p1_cogs in OCR has wrong digit (890.123.156 vs 890.123.456) -> MUST FAIL (no fuzzy!)
            {"id": "p1_cogs", "document": "page_01_narrow_table.png", "type": "amount", "value": "890.123.456"},
            # p1_code matches exact token
            {"id": "p1_code", "document": "page_01_narrow_table.png", "type": "code", "value": "BCTC-2026-NARROW"},
            # p3_contract_code in OCR was severely misread -> MUST FAIL (0 recovery)
            {"id": "p3_contract", "document": "page_03_confusing_chars.png", "type": "code", "value": "HD-2026-O0l1586B"},
            # p3_date matches
            {"id": "p3_date", "document": "page_03_confusing_chars.png", "type": "date", "value": "2026-01-15"},
        ]
    }

    report = score_ocr_text_recovery(gt_data, sample_ocr)

    assert report["evaluation_type"] == "upper_bound_token_recovery"
    assert "Upper-bound token recovery, NOT cell accuracy" in report["disclaimer"]
    assert report["total_fields"] == 5
    assert report["recovered_fields"] == 3  # p1_rev, p1_code, p3_date
    assert report["recovery_percent"] == 60.0

    field_map = {f["id"]: f for f in report["fields"]}
    assert field_map["p1_rev"]["recovered"] is True
    assert field_map["p1_cogs"]["recovered"] is False  # Wrong digit rejected
    assert field_map["p3_contract"]["recovered"] is False  # Confusing chars rejected
    assert field_map["p3_date"]["recovered"] is True


def test_split_ocr_pages() -> None:
    """Verifies page marker splitting into per-page dictionaries."""
    sample = (
        "===== page_01.png 100 chars\nContent 1\n"
        "===== page_02.png 200 chars\nContent 2\n"
    )
    pages = split_ocr_pages(sample)
    assert "page_01.png" in pages
    assert "page_02.png" in pages
    assert "Content 1" in pages["page_01.png"]
    assert "Content 2" in pages["page_02.png"]


# ---------------------------------------------------------------------------
# 7. Runner Prompt Builder & Security Tests
# ---------------------------------------------------------------------------

def test_prompt_builder_no_values_and_sanitizes_leaks() -> None:
    """Prompts must never include 'value' or 'numeric_value', and must sanitize name leaks."""
    fields = [
        {
            "id": "p3_contract_code",
            "name": "Mã hợp đồng chứa O0l1586B",
            "type": "code",
            "value": "HD-2026-O0l1586B",
        },
        {
            "id": "p3_serial_code",
            "name": "Số xê-ri thiết bị chứa 8568",
            "type": "code",
            "value": "SERIES-8568-2006",
        },
        {
            "id": "p1_rev",
            "name": "Doanh thu",
            "type": "amount",
            "value": "1.234.567.890",
            "numeric_value": 1234567890,
            "row": 1,
            "column": "B",
        },
    ]

    prompt = build_prompt_for_fields("page_03_confusing_chars.png", fields)

    # STRICT: value and numeric_value must NOT appear in prompt
    assert "1.234.567.890" not in prompt
    assert "1234567890" not in prompt
    assert "HD-2026-O0l1586B" not in prompt
    assert "SERIES-8568-2006" not in prompt

    # Leaks in name must be scrubbed
    assert "chứa O0l1586B" not in prompt
    assert "chứa 8568" not in prompt

    # Prompt instructions must be present
    assert "TUYỆT ĐỐI KHÔNG sử dụng công cụ" in prompt
    assert "JSON object" in prompt


def test_sanitize_field_name() -> None:
    """Verifies leak stripping from field names."""
    assert sanitize_field_name("Mã hợp đồng chứa O0l1586B", "HD-2026-O0l1586B") == "Mã hợp đồng"
    assert sanitize_field_name("Số xê-ri thiết bị chứa 8568", "SERIES-8568-2006") == "Số xê-ri thiết bị"
    assert sanitize_field_name("Lợi nhuận bình thường", "100") == "Lợi nhuận bình thường"


def test_prompt_table_cell_drops_name_no_cross_field_leak() -> None:
    """A table cell's name may be another field's GT answer: it must not reach the prompt."""
    sentinel = "SENTINEL_LABEL"
    fields = [
        {
            "id": "p4_revenue_quarter_text",
            "name": "Kỳ báo cáo",
            "type": "text",
            "value": sentinel,
            "row": 1,
            "column": "A",
        },
        {
            "id": "p4_revenue_amount",
            "name": f"Doanh thu bán hàng & dịch vụ {sentinel}",
            "type": "amount",
            "value": "1.234.567.890",
            "numeric_value": 1234567890,
            "row": 1,
            "column": "B",
        },
    ]

    prompt = build_prompt_for_fields("page_04_revenue_table.png", fields)

    # Whole prompt must be free of the cross-field leak and of any GT values.
    assert sentinel not in prompt
    assert "1.234.567.890" not in prompt
    assert "1234567890" not in prompt


def test_prompt_table_fields_are_addressed_by_position_only() -> None:
    """Table-cell specs carry exactly id/type/row/column — no name, ever."""
    fields = [
        {
            "id": "t_amount",
            "name": "Doanh thu bán hàng & dịch vụ Quý 2/2026",
            "type": "amount",
            "value": "999",
            "row": 1,
            "column": "B",
        },
        {
            "id": "t_row_only",
            "name": "Nhãn hàng 3",
            "type": "text",
            "value": "abc",
            "row": 3,
        },
    ]

    prompt = build_prompt_for_fields("page_07_table.png", fields)
    specs = json.loads(prompt.split("DANH SÁCH TRƯỜNG CẦN TRÍCH XUẤT:\n", 1)[1]
                       .split("\n\nQUY TẮC BẮT BUỘC:", 1)[0])

    by_id = {spec["id"]: spec for spec in specs}
    assert set(by_id["t_amount"]) == {"id", "type", "row", "column"}
    assert by_id["t_amount"]["row"] == 1
    assert by_id["t_amount"]["column"] == "B"
    # row-only table field still drops name, keeps its single coordinate
    assert set(by_id["t_row_only"]) == {"id", "type", "row"}
    assert "Doanh thu bán hàng" not in prompt
    assert "Nhãn hàng 3" not in prompt


def test_prompt_non_table_field_keeps_descriptive_name_without_value() -> None:
    """Non-table fields stay descriptive, but still never carry their own GT value."""
    fields = [
        {
            "id": "p1_title",
            "name": "Tiêu đề văn bản",
            "type": "text",
            "value": "QUYẾT ĐỊNH VỀ VIỆC BAN HÀNH QUY CHẾ",
        },
        {
            "id": "p1_code",
            "name": "Mã văn bản chứa 9182",
            "type": "code",
            "value": "9182/QĐ-UBND",
        },
    ]

    prompt = build_prompt_for_fields("page_01_header.png", fields)

    assert "Tiêu đề văn bản" in prompt
    assert "Mã văn bản" in prompt
    assert "QUYẾT ĐỊNH VỀ VIỆC BAN HÀNH QUY CHẾ" not in prompt
    assert "9182/QĐ-UBND" not in prompt
    assert "chứa 9182" not in prompt


# ---------------------------------------------------------------------------
# 8. Runner Execution Integration & Overwrite Guard
# ---------------------------------------------------------------------------

def test_runner_dry_run_and_overwrite_guard() -> None:
    """Runner dry-run produces structured outputs; existing output guard raises FileExistsError."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        gt_file = tmp_path / "ground_truth.json"
        bench_dir = tmp_path / "synthetic"
        bench_dir.mkdir()

        # Create dummy ground truth
        dummy_gt = {
            "fields": [
                {"id": "p1_item", "document": "page_01_narrow_table.png", "type": "amount", "value": "100"},
            ]
        }
        gt_file.write_text(json.dumps(dummy_gt), encoding="utf-8")
        (bench_dir / "page_01_narrow_table.png").write_bytes(b"dummy_png")

        out_dir = tmp_path / "results"

        # First run (dry-run)
        summary = execute_benchmark(
            ground_truth_path=gt_file,
            bench_dir=bench_dir,
            model="deepseek-v4.1-flash",
            effort="high",
            mode="images",
            output_dir=out_dir,
            dry_run=True,
            overwrite=False,
        )

        assert summary["metrics"]["quota_attempts"] == 1
        assert (out_dir / "run_summary.json").is_file()
        assert (out_dir / "raw_calls" / "call_01_page_01_narrow_table.json").is_file()

        # Attempt to run again into same out_dir without overwrite -> must raise FileExistsError
        with pytest.raises(FileExistsError):
            execute_benchmark(
                ground_truth_path=gt_file,
                bench_dir=bench_dir,
                model="deepseek-v4.1-flash",
                effort="high",
                mode="images",
                output_dir=out_dir,
                dry_run=True,
                overwrite=False,
            )

        # Run with overwrite=True succeeds
        summary_ow = execute_benchmark(
            ground_truth_path=gt_file,
            bench_dir=bench_dir,
            model="deepseek-v4.1-flash",
            effort="high",
            mode="images",
            output_dir=out_dir,
            dry_run=True,
            overwrite=True,
        )
        assert summary_ow["metrics"]["quota_attempts"] == 1


# ---------------------------------------------------------------------------
# 9. Runner scoping: per-call score, images vs pdf denominators
# ---------------------------------------------------------------------------

SCOPE_GT = {
    "schema_version": 1,
    "fields": [
        {"id": "p1_a", "document": "page_01_narrow_table.png", "type": "amount", "value": "100"},
        {"id": "p4_a", "document": "page_04_degraded_scan.png", "type": "amount", "value": "200"},
        {"id": "p5_a", "document": "page_05_multipage_p1.png", "type": "amount", "value": "300"},
        {"id": "p5_b", "document": "page_05_multipage_p1.png", "type": "date", "value": "2026-01-01"},
        {"id": "p6_a", "document": "page_06_multipage_p2.png", "type": "code", "value": "ABC"},
    ],
}


def _text_event(payload: str, ptype: str = "text", etype: str = "text") -> dict:
    return {"type": etype, "timestamp": 1, "part": {"type": ptype, "text": payload}}


def _stream(*events: dict) -> str:
    return "\n".join(json.dumps(ev) for ev in events)


def _envelope(stdout: str, status: str = "ok") -> str:
    return json.dumps(
        {
            "status": status,
            "vendor": "opencode",
            "model": "deepseek-v4.1-flash",
            "summary": "opencode completed successfully",
            "warnings": [],
            "stdout": stdout,
            "exit_code": 0,
        }
    )


@pytest.fixture
def scope_env(tmp_path):
    """Temp GT + bench dir for runner scoping tests."""
    gt_file = tmp_path / "ground_truth.json"
    gt_file.write_text(json.dumps(SCOPE_GT), encoding="utf-8")
    bench_dir = tmp_path / "synthetic"
    bench_dir.mkdir()
    for name in ("page_01_narrow_table.png", "page_04_degraded_scan.png",
                 "page_05_multipage_p1.png", "page_06_multipage_p2.png",
                 "multipage_contract.pdf"):
        (bench_dir / name).write_bytes(b"stub")
    return gt_file, bench_dir, tmp_path


def _run_with_fake_dispatch(monkeypatch, env, mode, fake):
    gt_file, bench_dir, tmp_path = env
    monkeypatch.setattr(run_mod, "run_dispatch_call", fake)
    out_dir = tmp_path / f"out_{mode}"
    summary = execute_benchmark(
        ground_truth_path=gt_file,
        bench_dir=bench_dir,
        model="deepseek-v4.1-flash",
        effort="high",
        mode=mode,
        output_dir=out_dir,
        timeout=600,
        overwrite=False,
        dry_run=False,
    )
    return summary, out_dir


def test_runner_pdf_mode_scores_pdf_fields_only(monkeypatch, scope_env):
    """mode=pdf must use the PDF field denominator, never the whole GT."""
    payload = json.dumps({"p5_a": "300", "p5_b": "2026-01-01", "p1_a": "100"})

    def fake(cmd, timeout=600, dry_run=False, wrapper_grace=120):
        return 0, _envelope(_stream(_text_event(payload))), "", 1.0

    summary, out_dir = _run_with_fake_dispatch(monkeypatch, scope_env, "pdf", fake)

    report = summary["score_report"]
    assert report["total_fields"] == 3  # p5_a, p5_b, p6_a — NOT all 5 GT fields
    assert report["correct_fields"] == 2
    assert summary["metrics"]["quota_attempts"] == 1

    # Scope summary keeps images and pdf separate
    assert summary["summary"]["images"] is None
    assert summary["summary"]["pdf"] == {
        "correct_fields": 2,
        "total_fields": 3,
        "accuracy_percent": 66.67,
    }

    call = summary["calls"][0]
    assert call["scope"] == "pdf"
    assert call["score"]["total_fields"] == 3
    # Off-task prediction (p1_a) is filtered out, never persisted or scored.
    assert set(call["parsed_predictions"]) == {"p5_a", "p5_b"}

    # Empty scratch cwd + JSON event format are wired into the dispatch argv.
    assert "--format" in call["command"]
    assert call["command"][call["command"].index("--format") + 1] == "json"
    assert "--cd" in call["command"]
    scratch = Path(call["command"][call["command"].index("--cd") + 1])
    assert scratch == out_dir / "scratch" / "multipage_contract_pdf"
    assert scratch.is_dir()
    assert list(scratch.iterdir()) == []


def test_runner_images_mode_scores_image_fields_only(monkeypatch, scope_env):
    """mode=images scores every PNG page field (page_05/page_06 included); pdf scope absent."""
    payload = json.dumps({"p1_a": "100", "p4_a": "200", "p5_a": "300"})

    def fake(cmd, timeout=600, dry_run=False, wrapper_grace=120):
        return 0, _envelope(_stream(_text_event(payload))), "", 1.0

    summary, _ = _run_with_fake_dispatch(monkeypatch, scope_env, "images", fake)

    # All four PNG docs are images scope: p1_a, p4_a, p5_a, p5_b, p6_a.
    assert summary["score_report"]["total_fields"] == 5
    # Correct: p1_a, p4_a, p5_a. Missing: p5_b, p6_a.
    assert summary["score_report"]["correct_fields"] == 3
    assert summary["summary"]["pdf"] is None
    assert summary["summary"]["images"] == {
        "correct_fields": 3,
        "total_fields": 5,
        "accuracy_percent": 60.0,
    }

    # Per-call filtering: each PNG call scores only its own field ids.
    per_call = {call["scope"] + ":" + call["document"]: call for call in summary["calls"]}
    assert len(per_call) == 4
    for call in summary["calls"]:
        assert call["scope"] == "images"
        assert call["score"]["total_fields"] == len(call["field_ids"])
        assert set(call["parsed_predictions"] or {}) <= set(call["field_ids"])

    assert per_call["images:page_01_narrow_table.png"]["field_ids"] == ["p1_a"]
    assert per_call["images:page_01_narrow_table.png"]["parsed_predictions"] == {"p1_a": "100"}
    assert per_call["images:page_04_degraded_scan.png"]["parsed_predictions"] == {"p4_a": "200"}
    # page_05 owns both p5_a and p5_b; the out-of-call p5_a copy is never leaked elsewhere.
    assert per_call["images:page_05_multipage_p1.png"]["field_ids"] == ["p5_a", "p5_b"]
    assert per_call["images:page_05_multipage_p1.png"]["parsed_predictions"] == {"p5_a": "300"}
    assert per_call["images:page_05_multipage_p1.png"]["score"]["total_fields"] == 2
    # p5_a is not scored on the page_06 call: nothing off-task is persisted.
    assert per_call["images:page_06_multipage_p2.png"]["field_ids"] == ["p6_a"]
    assert per_call["images:page_06_multipage_p2.png"]["status"] == "no_task_fields"
    assert per_call["images:page_06_multipage_p2.png"]["parsed_predictions"] is None
    assert per_call["images:page_06_multipage_p2.png"]["score"]["correct_fields"] == 0


def test_runner_all_mode_keeps_scopes_separate(monkeypatch, scope_env):
    """mode=all reports images and pdf separately; primary is the additive merge."""
    payload = json.dumps({"p1_a": "100", "p4_a": "999", "p5_a": "300", "p5_b": "2026-01-01", "p6_a": "ABC"})

    def fake(cmd, timeout=600, dry_run=False, wrapper_grace=120):
        return 0, _envelope(_stream(_text_event(payload))), "", 1.0

    summary, _ = _run_with_fake_dispatch(monkeypatch, scope_env, "all", fake)

    images = summary["summary"]["images"]
    pdf = summary["summary"]["pdf"]
    # images = all four PNG docs (5 fields, p4_a wrong); pdf = page_05+page_06 (3 fields).
    assert images["total_fields"] == 5 and images["correct_fields"] == 4
    assert pdf["total_fields"] == 3 and pdf["correct_fields"] == 3
    # Primary = additive merge of both scopes (5 + 3 fields, 4 + 3 correct).
    assert summary["score_report"]["total_fields"] == 8
    assert summary["score_report"]["correct_fields"] == 7


# ---------------------------------------------------------------------------
# 10. Strict dispatch acceptance (no envelope/error fallback, contamination)
# ---------------------------------------------------------------------------

def test_runner_rejects_dispatch_error_envelope_as_predictions(monkeypatch, scope_env):
    """status != ok ⇒ zero predictions; the envelope's stdout is never parsed."""
    payload = json.dumps({"p5_a": "300", "p5_b": "2026-01-01", "p6_a": "ABC"})

    def fake(cmd, timeout=600, dry_run=False, wrapper_grace=120):
        return 0, _envelope(_stream(_text_event(payload)), status="error"), "", 1.0

    summary, _ = _run_with_fake_dispatch(monkeypatch, scope_env, "pdf", fake)

    call = summary["calls"][0]
    assert call["status"] == "dispatch_error"
    assert call["parsed_predictions"] is None
    assert summary["score_report"]["correct_fields"] == 0
    assert summary["score_report"]["total_fields"] == 3


def test_runner_requires_returncode_zero(monkeypatch, scope_env):
    """retcode != 0 ⇒ predictions rejected even with a status=ok envelope."""
    payload = json.dumps({"p5_a": "300", "p5_b": "2026-01-01", "p6_a": "ABC"})

    def fake(cmd, timeout=600, dry_run=False, wrapper_grace=120):
        return 1, _envelope(_stream(_text_event(payload))), "boom", 1.0

    summary, _ = _run_with_fake_dispatch(monkeypatch, scope_env, "pdf", fake)

    assert summary["calls"][0]["status"] == "exit_1"
    assert summary["calls"][0]["parsed_predictions"] is None
    assert summary["score_report"]["correct_fields"] == 0


def test_runner_flags_tool_contamination_and_excludes_accuracy(monkeypatch, scope_env):
    """Tool events in the opencode stream ⇒ contaminated, excluded from accuracy."""
    payload = json.dumps({"p5_a": "300", "p5_b": "2026-01-01", "p6_a": "ABC"})
    stream = _stream(
        _text_event("Tôi sẽ đọc file.", etype="text", ptype="text"),
        {"type": "tool_use", "part": {"type": "tool", "tool": "read", "callID": "call_1",
                                       "state": {"input": {"path": "bench/vision/synthetic/ground_truth.json"}}}},
        _text_event(payload),
    )

    def fake(cmd, timeout=600, dry_run=False, wrapper_grace=120):
        return 0, _envelope(stream), "", 1.0

    summary, _ = _run_with_fake_dispatch(monkeypatch, scope_env, "pdf", fake)

    call = summary["calls"][0]
    assert call["contaminated"] is True
    assert call["status"] == "contaminated_tools"
    assert summary["metrics"]["contaminated_calls"] == 1
    assert summary["summary"]["excluded_contaminated_calls"] == ["multipage_contract_pdf"]
    # Predictions are kept as evidence but never counted as visual accuracy.
    assert call["parsed_predictions"] is not None
    assert summary["score_report"]["correct_fields"] == 0


def test_runner_wrapper_timeout_exceeds_vendor_timeout(monkeypatch):
    """Wrapper waits timeout+120 so dispatch can write diagnostics; one killer."""
    seen: dict[str, Any] = {}

    def fake_run(cmd, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(run_mod.subprocess, "run", fake_run)
    rc, _stdout, stderr, _latency = run_dispatch_call(["dispatch", "x"], timeout=600)

    assert rc == 124, stderr
    assert seen["timeout"] == 720
    assert "720s" in stderr


# ---------------------------------------------------------------------------
# 11. parse_json_response: assistant final text only, no envelope, dup keys
# ---------------------------------------------------------------------------

def test_json_parser_rejects_reasoning_thought_tool_and_error_events():
    answer = json.dumps({"p1_rev": "1"})
    stream = _stream(
        {"type": "reasoning", "part": {"type": "reasoning", "text": '{"p1_rev": "WRONG-FROM-REASONING"}'}},
        {"type": "thought", "part": {"type": "thought", "text": '{"p1_rev": "WRONG-FROM-THOUGHT"}'}},
        {"type": "tool_use", "part": {"type": "tool", "text": '{"p1_rev": "WRONG-FROM-TOOL"}', "tool": "read"}},
        {"type": "error", "part": {"type": "error", "text": '{"p1_rev": "WRONG-FROM-ERROR"}'}},
        _text_event(answer, ptype="text"),
    )
    parsed = parse_json_response(stream)
    assert parsed == {"p1_rev": "1"}
    assert extract_stream_text_from_jsonl(stream) == answer

    # No assistant text event at all ⇒ nothing accepted
    assert parse_json_response(_stream({"type": "error", "part": {"type": "error", "text": answer}})) is None
    assert parse_json_response(_stream({"type": "tool_use", "part": {"type": "tool", "text": answer}})) is None


def test_json_parser_accepts_single_event_line():
    single = json.dumps({"type": "text", "timestamp": 1, "part": {"type": "text", "text": '{"p1_a": "100"}'}})
    assert parse_json_response(single) == {"p1_a": "100"}


def test_json_parser_rejects_duplicate_keys_and_envelopes():
    dup = '{"p1_rev": "1", "p1_rev": "2"}'
    assert parse_json_response(dup) is None
    with pytest.raises(Exception):
        strict_json_loads(dup)

    envelope = json.dumps(
        {"status": "ok", "vendor": "opencode", "stdout": '{"p1_rev": "1"}', "warnings": []}
    )
    assert parse_json_response(envelope) is None
    # An envelope wrapped in a stream event is still not an answer.
    assert parse_json_response(_stream(_text_event(envelope))) is None


def test_detect_tool_events():
    clean = _stream(_text_event('{"p1_a": "1"}'))
    dirty = _stream(
        _text_event("đọc file"),
        {"type": "tool_use", "part": {"type": "tool", "tool": "read", "callID": "c1"}},
    )
    assert detect_tool_events(clean) is False
    assert detect_tool_events(dirty) is True
    assert detect_tool_events("") is False


# ---------------------------------------------------------------------------
# 12. Strict date parsing (no trailing-junk truncation)
# ---------------------------------------------------------------------------

def test_date_rejects_trailing_junk() -> None:
    assert parse_date("2026-01-01 nonsense") is None
    assert parse_date("2026-01-01T00:00:00") is None
    assert parse_date("2026-01-01 00:00") is None
    assert parse_date("2026-1-1") is None
    assert parse_date("01/01/26") is None
    assert parse_date(" 2026-01-01 ") == date(2026, 1, 1)


# ---------------------------------------------------------------------------
# 13. Baseline OCR amount recovery: signed boundaries
# ---------------------------------------------------------------------------

def test_ocr_amount_recovery_keeps_sign_and_token_boundaries() -> None:
    gt = {
        "fields": [
            {"id": "pos", "document": "p.png", "type": "amount", "value": "12345"},
            {"id": "neg", "document": "p.png", "type": "amount", "value": "-12345"},
        ]
    }

    # OCR has only the negative → the positive GT must NOT be "recovered".
    only_negative = "===== p.png 10 chars\nSố dư: -12345\n"
    rec = {f["id"]: f["recovered"] for f in score_ocr_text_recovery(gt, only_negative)["fields"]}
    assert rec["neg"] is True
    assert rec["pos"] is False

    # OCR has only the positive → the negative GT must NOT be "recovered".
    only_positive = "===== p.png 10 chars\nSố dư: 12345\n"
    rec = {f["id"]: f["recovered"] for f in score_ocr_text_recovery(gt, only_positive)["fields"]}
    assert rec["pos"] is True
    assert rec["neg"] is False

    # Digits embedded in a longer number are never split into a match.
    longer = "===== p.png 10 chars\nSố dư: 912345 và 123456\n"
    rec = {f["id"]: f["recovered"] for f in score_ocr_text_recovery(gt, longer)["fields"]}
    assert rec["pos"] is False
    assert rec["neg"] is False

    # Trailing punctuation does not break the token.
    punct = "===== p.png 10 chars\nSố dư: 12.345,\n"
    rec = {f["id"]: f["recovered"] for f in score_ocr_text_recovery(gt, punct)["fields"]}
    assert rec["pos"] is True


# ---------------------------------------------------------------------------
# 14. tool_result / role-shaped text events: contamination + no extraction
# ---------------------------------------------------------------------------

def test_tool_result_text_role_is_never_assistant_text() -> None:
    """role='tool_result' on a text/text event must be both flagged and never mined.

    Regression: an exact `role == "tool"` check let this payload through as the
    assistant final answer (parse succeeds, detect_tool_events False), so a tool
    result could be scored as vision accuracy.
    """
    answer = json.dumps({"p1_rev": "1"})
    for role in ("tool_result", "Tool_Result", "TOOL_RESULT", "tool-result", "tool", "TOOL_USE"):
        event = {"type": "text", "part": {"type": "text", "role": role, "text": answer}}
        stream = _stream(event)
        assert detect_tool_events(stream) is True, role
        assert detect_tool_events(json.dumps(event)) is True, role
        assert parse_json_response(stream) is None, role
        assert extract_stream_text_from_jsonl(stream) == "", role
        # Single event object as the whole input: same verdict.
        assert parse_json_response(json.dumps(event)) is None, role


def test_event_level_and_attribute_tool_markers_excluded() -> None:
    """Tool attribution anywhere on the event/part disqualifies the text."""
    answer = json.dumps({"p1_rev": "1"})
    events = [
        {"type": "text", "role": "tool_result", "part": {"type": "text", "text": answer}},
        # Event-level tool role wins over an innocent part role.
        {"type": "text", "role": "tool_result",
         "part": {"type": "text", "role": "assistant", "text": answer}},
        # Untyped part is only allowed when it carries no tool attribution.
        {"type": "text", "part": {"role": "tool_result", "text": answer}},
        {"type": "text", "part": {"type": "text", "tool_call_id": "c1", "text": answer}},
        {"type": "text", "part": {"type": "text", "tool": "read", "text": answer}},
        {"type": "text", "part": {"type": "Tool_Result", "text": answer}},
    ]
    for event in events:
        stream = _stream(event)
        assert detect_tool_events(stream) is True, event
        assert parse_json_response(stream) is None, event
        assert extract_stream_text_from_jsonl(stream) == "", event


def test_non_assistant_roles_and_event_types_excluded_without_tool_flag() -> None:
    """system/user/command/error/thought are not answers, and not contamination."""
    answer = json.dumps({"p1_rev": "1"})
    for role in ("system", "user", "command", "error", "thought", "reasoning"):
        stream = _stream({"type": "text", "part": {"type": "text", "role": role, "text": answer}})
        assert parse_json_response(stream) is None, role
        assert extract_stream_text_from_jsonl(stream) == "", role
        assert detect_tool_events(stream) is False, role

    for etype in ("thought", "reasoning", "error", "command", "system", "user", "step_finish"):
        stream = _stream({"type": etype, "part": {"type": "text", "text": answer}})
        assert parse_json_response(stream) is None, etype
        assert extract_stream_text_from_jsonl(stream) == "", etype
        assert detect_tool_events(stream) is False, etype

    # No recursive harvesting: nested blobs are never read as an answer.
    nested = json.dumps({
        "type": "text",
        "part": {"type": "text", "text": "", "content": answer,
                 "state": {"output": answer}},
    })
    assert parse_json_response(nested) is None
    assert extract_stream_text_from_jsonl(nested) == ""


def test_legit_text_events_and_direct_json_still_parse() -> None:
    """The fixes must not break real opencode text parts or bare JSON answers."""
    answer = json.dumps({"p1_rev": "1"})

    # opencode shape: type=text, part.type=text, no role.
    assert parse_json_response(_stream(_text_event(answer))) == {"p1_rev": "1"}
    assert extract_stream_text_from_jsonl(_stream(_text_event(answer))) == answer
    assert detect_tool_events(_stream(_text_event(answer))) is False

    # Explicit assistant/model roles stay valid.
    for role in ("assistant", "model", "Assistant", "MODEL"):
        event = {"type": "text", "part": {"type": "text", "role": role, "text": answer}}
        assert parse_json_response(_stream(event)) == {"p1_rev": "1"}, role
        assert detect_tool_events(_stream(event)) is False, role

    # Untyped part with plain text and no role is still assistant text.
    assert parse_json_response(_stream({"type": "text", "part": {"text": answer}})) == {"p1_rev": "1"}

    # Direct JSON answer with no event envelope.
    assert parse_json_response(answer) == {"p1_rev": "1"}
    assert parse_json_response("```json\n" + answer + "\n```") == {"p1_rev": "1"}


def test_mixed_stream_keeps_only_clean_text_but_flags_contamination() -> None:
    """A clean text event survives next to a tool_result carrying a wrong answer."""
    wrong = json.dumps({"p1_rev": "999"})
    right = json.dumps({"p1_rev": "1"})
    stream = _stream(
        {"type": "text", "part": {"type": "text", "role": "tool_result", "text": wrong}},
        _text_event(right),
    )
    assert detect_tool_events(stream) is True
    assert extract_stream_text_from_jsonl(stream) == right
    assert parse_json_response(stream) == {"p1_rev": "1"}


def test_runner_tool_result_event_with_valid_answers_is_contaminated(monkeypatch, scope_env):
    """One tool_result event carrying correct answers ⇒ contaminated, no predictions, 0 correct."""
    payload = json.dumps({"p5_a": "300", "p5_b": "2026-01-01", "p6_a": "ABC"})
    stream = _stream({"type": "text", "part": {"type": "text", "role": "tool_result", "text": payload}})

    def fake(cmd, timeout=600, dry_run=False, wrapper_grace=120):
        return 0, _envelope(stream), "", 1.0

    summary, _ = _run_with_fake_dispatch(monkeypatch, scope_env, "pdf", fake)

    call = summary["calls"][0]
    assert call["status"] == "contaminated_tools"
    assert call["contaminated"] is True
    assert call["contamination_status"] == "contaminated_tools"
    # The tool payload is not an answer: nothing parsed, nothing persisted.
    assert call["parsed_predictions"] is None
    assert call["score"]["correct_fields"] == 0
    assert call["score"]["total_fields"] == 3
    # Raw evidence is still persisted for audit.
    assert call["model_stdout"] == stream

    report = summary["score_report"]
    assert report["total_fields"] == 3
    assert report["correct_fields"] == 0
    assert report["accuracy_percent"] == 0.0
    assert summary["metrics"]["contaminated_calls"] == 1
    assert summary["metrics"]["inference_success"] == 0
    assert summary["summary"]["excluded_contaminated_calls"] == ["multipage_contract_pdf"]
    assert summary["summary"]["pdf"] == {
        "correct_fields": 0,
        "total_fields": 3,
        "accuracy_percent": 0.0,
    }
