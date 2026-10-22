#!/usr/bin/env python3
"""Deterministic typed scoring engine for synthetic vision benchmark.

Evaluates model extractions against ground truth strictly by data type:
  - amount: Exact Decimal value comparison; supports VN dot thousands (1.234.567.890),
            parentheses for negative numbers ((12.345) -> -12345), standard negative sign (-12345).
            Strict rejection: No permissive stripping of letters, no booleans, no NaN/Inf.
  - date:   Valid calendar date comparison (ISO YYYY-MM-DD or Vietnamese DD/MM/YYYY).
            Distinguishes tricky years (e.g. 2026 vs 2006). Rejects invalid dates.
  - code:   EXACT string equality. Case-sensitive, exact character match (e.g. 0 vs O, 1 vs l).
  - text:   Case-sensitive string equality with Unicode NFC whitespace normalization ONLY.

Honest baseline OCR metric:
  --ocr-text evaluates upper-bound token/line recovery on raw OCR dumps (split by page markers),
  clearly labeled as upper-bound recovery, NOT cell or field association accuracy.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import re
import sys
from typing import Any
import unicodedata


# ---------------------------------------------------------------------------
# Strict Typed Parsers
# ---------------------------------------------------------------------------

# The ONLY currency units the amount parser tolerates, and only as a single
# trailing token after whitespace. Everything else (USD, EUR, "VN", prefix
# forms like "VND12345", glued forms like "12345VND") must still be rejected.
_CURRENCY_SUFFIX_RE = re.compile(r"^(.*\S)\s+(?:vnd|vnđ|đ)$", re.DOTALL)

# Internal whitespace is accepted only as thousands-group separators.
_SPACE_GROUPED_RE = re.compile(r"^\d{1,3}(?: \d{3})+(?:,\d+)?$")


def _strip_currency_suffix(s: str) -> str:
    """Return `s` with one whitelisted trailing currency unit removed.

    The match runs on the case-folded string so "VND", "vnd", "VNĐ", "vnđ"
    and "Đ" all qualify, then returns the numeric body. No match (prefix unit,
    glued unit, unknown currency, repeated unit, no whitespace) returns `s`
    unchanged so the caller's letter rejection fails it.
    """
    m = _CURRENCY_SUFFIX_RE.match(s.casefold())
    if m is None:
        return s
    return m.group(1).strip()


def parse_amount(val: Any) -> Decimal | None:
    """Parse an amount into a Decimal with strict validation.

    Accepts:
      - Integers, floats (finite, non-NaN)
      - Formatted strings with Vietnamese dot thousands: "1.234.567.890" -> 1234567890
      - Accounting negative in parentheses: "(12.345)" -> -12345
      - Standard negative sign: "-12.345" -> -12345
      - Standard decimal strings: "12345.50" or VN decimal comma "12345,50"
      - ONE trailing currency unit from the exact whitelist VND / VNĐ / đ,
        case-insensitive, whitespace-separated: "56.810.000 VND" -> 56810000,
        "(12.345) VNĐ" -> -12345. Only at the very end, only after whitespace,
        and only once.

    Strict rejections (returns None):
      - Booleans (True / False)
      - NaN, inf, -inf
      - Any other letters or alphabet characters (no permissive stripping):
        "123abc", "VND 12345", "12345VND", "123 VND xyz", "123 USD"
      - Multiple amounts or repeated units: "123 VND 456", "123 vnd vnd"
      - Malformed thousands groupings or multiple conflicting separators
      - Conflicting signs: "-(12.345)", "(-12.345)"
    """
    if val is None or isinstance(val, bool):
        return None

    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return None
        try:
            return Decimal(str(val))
        except (InvalidOperation, ValueError):
            return None

    if not isinstance(val, str):
        return None

    s = val.strip()
    if not s:
        return None

    # Reject NaN / Infinity
    if re.search(r"(?i)\b(nan|infinity|inf)\b", s):
        return None

    # Strip exactly one whitelisted trailing currency unit before the letter
    # rejection below, which would otherwise reject every suffixed amount.
    s = _strip_currency_suffix(s)
    if not s:
        return None

    # Reject if string contains any alphabetical or word characters
    # (Strict: NO permissive stripping of letters allowed)
    if re.search(r"[a-zA-Z\u00C0-\u024F\u1EA0-\u1EF9]", s):
        return None

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()
    elif s.startswith("-"):
        negative = True
        s = s[1:].strip()
    elif s.startswith("+"):
        s = s[1:].strip()

    # After sign/parens removal, must only contain digits, dots, commas, spaces
    if not re.match(r"^[\d.,\s]+$", s):
        return None

    # Spaces may only be thousands-group separators ("56 810 000"). A plain
    # concatenation would silently turn "12345 67890" into 1234567890, i.e.
    # accept two amounts as one wrong number, so anything else is rejected.
    s = re.sub(r"\s+", " ", s)
    if " " in s:
        if _SPACE_GROUPED_RE.fullmatch(s) is None:
            return None
        s = s.replace(" ", ".")
    if not s:
        return None

    # Handle thousands vs decimal separators
    # Pattern 1: VN dot thousands with optional decimal comma: 1.234.567 or 1.234.567,89
    if re.match(r"^\d{1,3}(\.\d{3})+(,\d+)?$", s):
        s = s.replace(".", "").replace(",", ".")
    # Pattern 2: US comma thousands with optional decimal dot: 1,234,567 or 1,234,567.89
    elif re.match(r"^\d{1,3}(,\d{3})+(\.\d+)?$", s):
        s = s.replace(",", "")
    # Pattern 3: VN single decimal comma: 12345,67
    elif re.match(r"^\d+,\d+$", s):
        s = s.replace(",", ".")
    # Pattern 4: Standard integer or decimal dot: 1234567890 or 12345.67
    elif re.match(r"^\d+(\.\d+)?$", s):
        pass
    else:
        # Ambiguous or invalid format (e.g. "1.2.3" or "1,,234")
        return None

    try:
        res = Decimal(s)
        if res.is_nan() or res.is_infinite():
            return None
        return -res if negative else res
    except (InvalidOperation, ValueError):
        return None


_ALLOWED_DATE_FORMATS = (
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "%Y-%m-%d"),
    (re.compile(r"\d{2}/\d{2}/\d{4}"), "%d/%m/%Y"),
    (re.compile(r"\d{2}-\d{2}-\d{4}"), "%d-%m-%Y"),
    (re.compile(r"\d{4}/\d{2}/\d{2}"), "%Y/%m/%d"),
)


def parse_date(val: Any) -> date | None:
    """Parse a date into a valid calendar date object.

    Accepts ONLY the four full-string formats below (ISO YYYY-MM-DD,
    DD/MM/YYYY, DD-MM-YYYY, YYYY/MM/DD). No truncation of trailing junk:
    '2026-01-01 nonsense' and '2026-01-01T00:00:00' are rejected outright.
    Strict calendar validation ensures leap years and valid month/day bounds.
    """
    if val is None or isinstance(val, bool) or not isinstance(val, str):
        return None

    s = val.strip()
    if not s:
        return None

    for pattern, fmt in _ALLOWED_DATE_FORMATS:
        if pattern.fullmatch(s) is None:
            continue
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            return None
        return dt.date()

    return None


def parse_code(val: Any) -> str | None:
    """Parse code with EXACT string equality (case-sensitive, character-for-character)."""
    if val is None or isinstance(val, bool) or not isinstance(val, str):
        return None
    return str(val)


def parse_text(val: Any) -> str | None:
    """Parse text with Unicode NFC and whitespace normalization ONLY (case-sensitive)."""
    if val is None or isinstance(val, bool) or not isinstance(val, str):
        return None
    normalized = unicodedata.normalize("NFC", str(val))
    # Normalize internal whitespace sequences to a single space and strip edges
    return " ".join(normalized.split())


# ---------------------------------------------------------------------------
# JSON Output Parser (strict: assistant final text only, no envelopes)
# ---------------------------------------------------------------------------

class DuplicateJSONKeyError(ValueError):
    """Raised when a JSON object repeats the same key."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise DuplicateJSONKeyError(f"duplicate JSON key: {key!r}")
        out[key] = value
    return out


def strict_json_loads(text: str) -> Any:
    """json.loads that fails on duplicate object keys (no silent last-wins)."""
    return json.loads(text, object_pairs_hook=_reject_duplicate_keys)


# Field names that only ever appear in a PolyKit dispatch result envelope —
# never in a model answer mapping field id -> value.
_ENVELOPE_MARKER_KEYS = frozenset(
    {"vendor", "exit_code", "served_model", "warnings", "stdout", "stderr", "reason", "latency_ms"}
)

# Event type names emitted by `opencode run --format json`.
_EVENT_TYPE_NAMES = frozenset(
    {"text", "tool_use", "tool_result", "step_start", "step_finish", "error", "reasoning", "thinking"}
)


def looks_like_dispatch_envelope(obj: Any) -> bool:
    """True if `obj` looks like a dispatch result envelope rather than predictions."""
    if not isinstance(obj, dict):
        return False
    keys = {str(k).lower() for k in obj}
    if keys & _ENVELOPE_MARKER_KEYS:
        return True
    status = str(obj.get("status", "")).strip().lower()
    return "summary" in keys and status in {"ok", "error", "skipped", "blocked", "failed"}


def is_event_object(obj: Any) -> bool:
    """True if `obj` is a single stream event object (not an answer mapping)."""
    if not isinstance(obj, dict):
        return False
    etype = obj.get("type")
    if not isinstance(etype, str):
        return False
    if "part" in obj or "event" in obj:
        return True
    return etype.strip().lower() in _EVENT_TYPE_NAMES


# Roles an assistant FINAL text event may carry. Anything else — "system",
# "user", "tool", "tool_result", "command", "error", ... — is not an answer.
_FINAL_TEXT_ROLES = frozenset({"", "assistant", "model"})


def _casefold_attr(value: Any) -> str:
    """Case-fold one event attribute to a bare token (absent -> "")."""
    if value is None:
        return ""
    return str(value).strip().casefold()


def _mentions_tool(value: Any) -> bool:
    """True if an attribute names a tool in ANY casing/spelling.

    Substring on the casefolded token, so "tool", "TOOL_USE", "Tool-Result"
    and "tool_result" all qualify. An exact `== "tool"` comparison let
    role="tool_result" pass as assistant output and as a clean call.
    """
    return "tool" in _casefold_attr(value)


def _has_tool_marker(node: Any) -> bool:
    """True if a stream event carries any tool attribution (shallow, no recursion)."""
    if not isinstance(node, dict):
        return False
    if _mentions_tool(node.get("type")) or _mentions_tool(node.get("role")):
        return True
    if (
        node.get("tool")
        or node.get("toolName")
        or node.get("callID")
        or node.get("tool_call_id")
    ):
        return True
    part = node.get("part")
    if isinstance(part, dict):
        if _mentions_tool(part.get("type")) or _mentions_tool(part.get("role")):
            return True
        if (
            part.get("tool")
            or part.get("toolName")
            or part.get("callID")
            or part.get("tool_call_id")
        ):
            return True
    return False


def _event_assistant_text(event: Any) -> str | None:
    """Return assistant FINAL text carried by one stream event, else None.

    Allowlist only, and deliberately shallow — nothing is harvested by
    recursing into nested content/state/output blobs:
      - event type must be exactly "text" (thought / reasoning / error /
        command / system / user / tool events are never candidates),
      - `part` must be present, and if it is typed it must be exactly "text",
      - no tool attribution anywhere on the event or its part, so
        role="tool_result" / part.type="tool_use" / tool / callID carriers
        are never read as an answer,
      - role must be absent, "assistant" or "model".
    """
    if not isinstance(event, dict):
        return None
    if _casefold_attr(event.get("type")) != "text":
        return None
    part = event.get("part")
    if not isinstance(part, dict):
        return None
    ptype = _casefold_attr(part.get("type"))
    if ptype and ptype != "text":
        return None
    if _has_tool_marker(event):
        return None
    for role in (_casefold_attr(part.get("role")), _casefold_attr(event.get("role"))):
        if role not in _FINAL_TEXT_ROLES:
            return None
    text = part.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    return text


def _looks_like_event_stream(raw: str) -> bool:
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or not stripped.startswith("{"):
            continue
        try:
            obj = strict_json_loads(stripped)
        except Exception:
            return False
        return isinstance(obj, dict) and isinstance(obj.get("type"), str)
    return False


def _parse_event_stream(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or not stripped.startswith("{"):
            continue
        try:
            obj = strict_json_loads(stripped)
        except Exception:
            # Not a decodable event: never mine text from it.
            continue
        if isinstance(obj, dict):
            events.append(obj)
    return events


def extract_stream_text_from_jsonl(raw: str) -> str:
    """Extract ONLY assistant final text from opencode JSONL stream events.

    Kept under its original name for callers, but the old permissive scan
    (which mined thought/reasoning/message/error/tool payloads) is gone.
    """
    if not isinstance(raw, str) or not raw.strip():
        return ""
    events = _parse_event_stream(raw)
    texts = [t for t in (_event_assistant_text(e) for e in events) if t]
    return "\n".join(texts)


def detect_tool_events(raw_text: str) -> bool:
    """Detect tool usage (read/bash/...) inside an opencode JSONL event stream.

    Unsandboxed runs cannot be trusted to ignore tools: if the model invoked
    any tool we must flag the call as contaminated instead of counting its
    predictions as visual accuracy. Role/type matching is casefolded
    substring, so `tool`, `tool_use`, `tool_result`, `Tool-Result` all count.
    """
    if not isinstance(raw_text, str) or not raw_text.strip():
        return False

    stripped = raw_text.strip()
    try:
        single = strict_json_loads(stripped)
    except Exception:
        single = None
    if isinstance(single, dict) and is_event_object(single):
        return _has_tool_marker(single)

    return any(_has_tool_marker(ev) for ev in _parse_event_stream(raw_text))


def _accept_prediction_object(obj: Any) -> dict[str, Any] | None:
    if not isinstance(obj, dict):
        return None
    if is_event_object(obj):
        return None
    if looks_like_dispatch_envelope(obj):
        return None
    return obj


def _parse_model_content(text: str) -> dict[str, Any] | None:
    """Decode a model answer text into a dict; None if absent/invalid/envelope."""
    if not text or not text.strip():
        return None
    body = text.strip()

    # 1. Whole text is a JSON value (may be pretty-printed over several lines).
    try:
        obj = strict_json_loads(body)
    except Exception:
        obj = None
    if isinstance(obj, (dict, list)):
        return _accept_prediction_object(obj) if isinstance(obj, dict) else None

    # 2. Markdown fenced code block(s).
    fence_pattern = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)
    for block in fence_pattern.findall(body):
        try:
            obj = strict_json_loads(block)
        except Exception:
            continue
        accepted = _accept_prediction_object(obj)
        if accepted is not None:
            return accepted

    # 3. Outermost '{' ... '}' inside surrounding prose.
    first_brace = body.find("{")
    last_brace = body.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            obj = strict_json_loads(body[first_brace : last_brace + 1])
        except Exception:
            return None
        return _accept_prediction_object(obj)

    return None


def _parse_from_events(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    texts = [t for t in (_event_assistant_text(e) for e in events) if t]
    if not texts:
        return None
    # Prefer the FINAL assistant text event; fall back to the joined text
    # (multi-step answers may split one JSON object across text events).
    for candidate in (texts[-1], "\n".join(texts)):
        parsed = _parse_model_content(candidate)
        if parsed is not None:
            return parsed
    return None


def parse_json_response(raw_text: str) -> dict[str, Any] | None:
    """Parse a model answer into a field-id -> value dict, strictly.

    Accepted inputs:
      1. Assistant final text that is a JSON object (plain, fenced, or embedded
         in prose).
      2. opencode `--format json` event stream: ONLY `type == "text"` events
         (assistant final text). thought/reasoning/error/tool events are never
         mined, and a single event object on one line is handled the same way.

    Rejected (returns None):
      - Dispatch result envelopes (`{"status": "ok", "stdout": ...}`).
      - Duplicate JSON keys.
      - Arrays, scalars, malformed JSON, streams with no assistant text.
    """
    if not raw_text or not isinstance(raw_text, str):
        return None

    body = raw_text.strip()
    if not body:
        return None

    # Whole input is one JSON value (possibly pretty-printed across lines).
    try:
        whole = strict_json_loads(body)
    except Exception:
        whole = None
    if isinstance(whole, dict):
        if is_event_object(whole):
            return _parse_from_events([whole])
        return _accept_prediction_object(whole)
    if isinstance(whole, list):
        return None

    # JSONL event stream from `--format json`.
    if _looks_like_event_stream(body):
        return _parse_from_events(_parse_event_stream(body))

    # Plain assistant text (prose / fenced JSON / embedded object).
    return _parse_model_content(body)


# ---------------------------------------------------------------------------
# Comparison & Scoring
# ---------------------------------------------------------------------------

def compare_field(
    field_type: str,
    gt_val: Any,
    pred_val: Any,
) -> tuple[bool, Any, Any, str | None]:
    """Compare a single ground truth field against prediction based on field type.

    Returns:
      (correct: bool, parsed_gt, parsed_pred, error_reason: str | None)
    """
    if pred_val is None:
        return False, gt_val, None, "missing"

    if field_type == "amount":
        pgt = parse_amount(gt_val)
        ppred = parse_amount(pred_val)
        if pgt is None:
            return False, None, ppred, "invalid_ground_truth"
        if ppred is None:
            return False, str(pgt), None, "invalid_amount_format"
        correct = (pgt == ppred)
        return correct, str(pgt), str(ppred), (None if correct else "amount_mismatch")

    if field_type == "date":
        pgt = parse_date(gt_val)
        ppred = parse_date(pred_val)
        if pgt is None:
            return False, None, ppred, "invalid_ground_truth"
        if ppred is None:
            return False, str(pgt), None, "invalid_date_format"
        correct = (pgt == ppred)
        return correct, str(pgt), str(ppred), (None if correct else "date_mismatch")

    if field_type == "code":
        pgt = parse_code(gt_val)
        ppred = parse_code(pred_val)
        if pgt is None:
            return False, None, ppred, "invalid_ground_truth"
        if ppred is None:
            return False, pgt, None, "invalid_code_format"
        correct = (pgt == ppred)
        return correct, pgt, ppred, (None if correct else "code_mismatch")

    if field_type == "text":
        pgt = parse_text(gt_val)
        ppred = parse_text(pred_val)
        if pgt is None:
            return False, None, ppred, "invalid_ground_truth"
        if ppred is None:
            return False, pgt, None, "invalid_text_format"
        correct = (pgt == ppred)
        return correct, pgt, ppred, (None if correct else "text_mismatch")

    # Unknown type fallback
    correct = (str(gt_val) == str(pred_val))
    return correct, gt_val, pred_val, (None if correct else "unknown_type_mismatch")


def score_predictions(
    ground_truth_data: dict[str, Any],
    predictions: dict[str, Any],
    field_ids: list[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Score model predictions against ground truth annotations.

    Strict rules:
      - Field ID mapping only. Never use ground truth to backfill missing predictions.
      - Missing or invalid fields are counted as WRONG, not excluded from total.
      - Grouped outputs per document and per field type.
      - `field_ids` restricts the denominator to the fields actually put to the
        model in this call/scope (images vs PDF), so a PDF-only run can never be
        scored against image fields it was never asked about.
    """
    all_fields = ground_truth_data.get("fields", [])
    if field_ids is not None:
        allowed_ids = set(field_ids)
        fields = [f for f in all_fields if f.get("id") in allowed_ids]
        predictions = {k: v for k, v in predictions.items() if k in allowed_ids}
    else:
        allowed_ids = None
        fields = all_fields
    per_field: list[dict[str, Any]] = []

    doc_stats: dict[str, dict[str, int]] = {}
    type_stats: dict[str, dict[str, int]] = {}

    total_correct = 0
    total_fields = len(fields)

    for field in fields:
        fid = field["id"]
        doc = field.get("document", "unknown")
        ftype = field.get("type", "unknown")
        gt_val = field.get("value")

        if doc not in doc_stats:
            doc_stats[doc] = {"correct": 0, "total": 0}
        if ftype not in type_stats:
            type_stats[ftype] = {"correct": 0, "total": 0}

        doc_stats[doc]["total"] += 1
        type_stats[ftype]["total"] += 1

        pred_val = predictions.get(fid)
        correct, parsed_gt, parsed_pred, error_reason = compare_field(ftype, gt_val, pred_val)

        if correct:
            total_correct += 1
            doc_stats[doc]["correct"] += 1
            type_stats[ftype]["correct"] += 1

        record: dict[str, Any] = {
            "id": fid,
            "document": doc,
            "page": field.get("page"),
            "name": field.get("name"),
            "type": ftype,
            "ground_truth_raw": gt_val,
            "prediction_raw": pred_val,
            "parsed_gt": parsed_gt,
            "parsed_pred": parsed_pred,
            "correct": correct,
            "error_reason": error_reason,
        }
        if "row" in field:
            record["row"] = field["row"]
        if "column" in field:
            record["column"] = field["column"]

        per_field.append(record)

    def _format_stats(stats: dict[str, dict[str, int]]) -> dict[str, dict[str, Any]]:
        out = {}
        for k, v in stats.items():
            tot = v["total"]
            cor = v["correct"]
            pct = (cor / tot * 100.0) if tot > 0 else 0.0
            out[k] = {
                "correct": cor,
                "total": tot,
                "percent": round(pct, 2),
            }
        return out

    overall_pct = (total_correct / total_fields * 100.0) if total_fields > 0 else 0.0

    return {
        "evaluation_type": "deterministic_typed_accuracy",
        "scope_field_ids": sorted(allowed_ids) if allowed_ids is not None else None,
        "total_fields": total_fields,
        "correct_fields": total_correct,
        "accuracy_percent": round(overall_pct, 2),
        "by_document": _format_stats(doc_stats),
        "by_type": _format_stats(type_stats),
        "fields": per_field,
    }


# ---------------------------------------------------------------------------
# Baseline vnocr Token Recovery (Separate Honest Metric)
# ---------------------------------------------------------------------------

# Amount token with strict signed boundaries. A leading '-'/'+' or accounting
# parentheses belong to the token, and a digit run can never be cut out of a
# longer number or glued to letters: '-12345' != '12345', '912345' != '12345'.
_AMOUNT_TOKEN_RE = re.compile(
    r"(?<![\w.,+(-])(?:\(\s*[-+]?\s*\d[\d.,]*\d\s*\)|[-+]?\d[\d.,]*\d|[-+]?\d)(?![\w])"
)


def split_ocr_pages(ocr_text: str) -> dict[str, str]:
    """Split raw OCR text dump by page markers into a dictionary: document -> page_text.

    Expected marker pattern:
      ===== page_01_narrow_table.png 1068 ký tự [tin cậy=0.9950]
    """
    marker_pattern = re.compile(r"^=====\s+([^\s]+)(?:\.png|\.pdf)?.*$", re.MULTILINE)
    splits = list(marker_pattern.finditer(ocr_text))
    pages: dict[str, str] = {}

    if not splits:
        # Fallback if no page markers found: treat as single global text
        pages["*"] = ocr_text
        return pages

    for i, match in enumerate(splits):
        doc_name = match.group(1).strip()
        if not doc_name.endswith(".png") and not doc_name.endswith(".pdf"):
            doc_name += ".png"
        start_idx = match.end()
        end_idx = splits[i + 1].start() if (i + 1 < len(splits)) else len(ocr_text)
        page_content = ocr_text[start_idx:end_idx].strip()
        pages[doc_name] = page_content

    return pages


def score_ocr_text_recovery(
    ground_truth_data: dict[str, Any],
    ocr_raw_text: str,
) -> dict[str, Any]:
    """Evaluate upper-bound token/line recovery of raw OCR text against ground truth.

    DISCLAIMER:
      This is an UPPER-BOUND token recovery metric, NOT cell or field association accuracy.
      Raw OCR engines do not associate values to specific field IDs or table rows.
      Duplicate tokens cannot prove correct row alignment.
    """
    pages = split_ocr_pages(ocr_raw_text)
    fields = ground_truth_data.get("fields", [])

    per_field: list[dict[str, Any]] = []
    doc_stats: dict[str, dict[str, int]] = {}
    type_stats: dict[str, dict[str, int]] = {}

    total_recovered = 0
    total_fields = len(fields)

    for field in fields:
        fid = field["id"]
        doc = field.get("document", "unknown")
        ftype = field.get("type", "unknown")
        gt_val = field.get("value")

        if doc not in doc_stats:
            doc_stats[doc] = {"recovered": 0, "total": 0}
        if ftype not in type_stats:
            type_stats[ftype] = {"recovered": 0, "total": 0}

        doc_stats[doc]["total"] += 1
        type_stats[ftype]["total"] += 1

        page_text = pages.get(doc, pages.get("*", ""))
        recovered = False
        matched_candidate: str | None = None

        if page_text:
            if ftype == "amount":
                pgt = parse_amount(gt_val)
                if pgt is not None:
                    # Signed token boundaries: a minus sign is part of the token,
                    # and digits glued to other digits/letters are never split.
                    # Prevents -12345 counting as +12345 and 12345 "recovered"
                    # from 123456 / 912345 substrings.
                    for cand in _AMOUNT_TOKEN_RE.findall(page_text):
                        pcand = parse_amount(cand)
                        if pcand is not None and pcand == pgt:
                            recovered = True
                            matched_candidate = cand
                            break

            elif ftype == "date":
                pgt = parse_date(gt_val)
                if pgt is not None:
                    cand_dates = re.findall(r"\b\d{1,4}[/-]\d{1,2}[/-]\d{2,4}\b", page_text)
                    for cand in cand_dates:
                        pcand = parse_date(cand)
                        if pcand is not None and pcand == pgt:
                            recovered = True
                            matched_candidate = cand
                            break

            elif ftype == "code":
                pgt = parse_code(gt_val)
                if pgt is not None:
                    # Token-level exact match (no fuzzy!)
                    cand_words = re.findall(r"[^\s]+", page_text)
                    for cand in cand_words:
                        clean_cand = cand.strip(".,;:()[]{}\"'")
                        if parse_code(clean_cand) == pgt:
                            recovered = True
                            matched_candidate = clean_cand
                            break

            elif ftype == "text":
                pgt = parse_text(gt_val)
                if pgt is not None:
                    norm_page = parse_text(page_text) or ""
                    if pgt in norm_page:
                        recovered = True
                        matched_candidate = pgt
                    else:
                        for line in page_text.splitlines():
                            norm_line = parse_text(line) or ""
                            if pgt == norm_line or (len(pgt) > 10 and pgt in norm_line):
                                recovered = True
                                matched_candidate = line.strip()
                                break

        if recovered:
            total_recovered += 1
            doc_stats[doc]["recovered"] += 1
            type_stats[ftype]["recovered"] += 1

        per_field.append({
            "id": fid,
            "document": doc,
            "type": ftype,
            "ground_truth": gt_val,
            "recovered": recovered,
            "matched_candidate": matched_candidate,
        })

    def _format_stats(stats: dict[str, dict[str, int]]) -> dict[str, dict[str, Any]]:
        out = {}
        for k, v in stats.items():
            tot = v["total"]
            rec = v["recovered"]
            pct = (rec / tot * 100.0) if tot > 0 else 0.0
            out[k] = {
                "recovered": rec,
                "total": tot,
                "percent": round(pct, 2),
            }
        return out

    overall_pct = (total_recovered / total_fields * 100.0) if total_fields > 0 else 0.0

    return {
        "evaluation_type": "upper_bound_token_recovery",
        "disclaimer": (
            "Upper-bound token recovery, NOT cell accuracy. "
            "Raw OCR does not associate extracted tokens to field IDs or table cells. "
            "Duplicate tokens cannot prove row/column association."
        ),
        "total_fields": total_fields,
        "recovered_fields": total_recovered,
        "recovery_percent": round(overall_pct, 2),
        "by_document": _format_stats(doc_stats),
        "by_type": _format_stats(type_stats),
        "fields": per_field,
    }


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic typed vision benchmark scorer.")
    parser.add_argument(
        "--ground-truth", "-g",
        required=True,
        help="Path to ground_truth.json",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--prediction", "-p",
        help="Path to prediction JSON / JSONL file or '-' for stdin",
    )
    group.add_argument(
        "--ocr-text",
        help="Path to raw vnocr text dump for upper-bound token recovery evaluation",
    )
    parser.add_argument(
        "--output", "-o",
        help="Path to save output JSON report",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print human-readable summary table to stdout",
    )

    args = parser.parse_args()

    gt_path = Path(args.ground_truth)
    if not gt_path.is_file():
        sys.stderr.write(f"Error: ground truth file not found: {gt_path}\n")
        return 1

    with open(gt_path, encoding="utf-8") as f:
        gt_data = json.load(f)

    report: dict[str, Any]

    if args.ocr_text:
        ocr_path = Path(args.ocr_text)
        if not ocr_path.is_file():
            sys.stderr.write(f"Error: OCR text file not found: {ocr_path}\n")
            return 1
        with open(ocr_path, encoding="utf-8") as f:
            ocr_text = f.read()
        report = score_ocr_text_recovery(gt_data, ocr_text)

    else:
        if args.prediction == "-":
            raw_input = sys.stdin.read()
        else:
            p_path = Path(args.prediction)
            if not p_path.is_file():
                sys.stderr.write(f"Error: prediction file not found: {p_path}\n")
                return 1
            with open(p_path, encoding="utf-8") as f:
                raw_input = f.read()

        parsed_preds = parse_json_response(raw_input)
        if parsed_preds is None:
            sys.stderr.write("Warning: failed to parse valid JSON object from predictions.\n")
            parsed_preds = {}

        report = score_predictions(gt_data, parsed_preds)

    report_json = json.dumps(report, ensure_ascii=False, indent=2)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report_json + "\n")
        sys.stderr.write(f"Report saved to: {out_path}\n")

    if args.summary or not args.output:
        eval_type = report["evaluation_type"]
        print(f"\n=== Vision Benchmark Evaluation [{eval_type}] ===")
        if "disclaimer" in report:
            print(f"NOTE: {report['disclaimer']}\n")

        if eval_type == "deterministic_typed_accuracy":
            print(f"Overall Accuracy: {report['correct_fields']}/{report['total_fields']} ({report['accuracy_percent']}%)")
        else:
            print(f"Overall Recovery: {report['recovered_fields']}/{report['total_fields']} ({report['recovery_percent']}%)")

        print("\n--- By Document ---")
        for doc, st in report["by_document"].items():
            num = st.get("correct", st.get("recovered", 0))
            print(f"  {doc:35s}: {num:2d}/{st['total']:2d} ({st['percent']:6.2f}%)")

        print("\n--- By Type ---")
        for ftype, st in report["by_type"].items():
            num = st.get("correct", st.get("recovered", 0))
            print(f"  {ftype:15s}: {num:2d}/{st['total']:2d} ({st['percent']:6.2f}%)")
        print("=" * 50 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
