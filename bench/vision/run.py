#!/usr/bin/env python3
"""Synthetic vision benchmark runner CLI.

Executes vision evaluations against synthetic documents using bin/dispatch.py:
  - Supported models:
      * deepseek-v4.1-flash (default effort: high)
      * glm-5.3-flash (default effort: max)
  - Execution modes:
      * images: 6 PNG synthetic pages evaluated individually
      * pdf: 2-page multipage_contract.pdf (direct for GLM, converted for DeepSeek)
      * all: both individual PNGs and the multipage PDF
  - Strict security & prompt hygiene:
      * Prompt contains ONLY id, type, name, and optional row/column.
      * Strictly NO value or numeric_value in prompts.
      * Answer leaks in field names are actively scrubbed.
      * Unsandboxed harness limitation is explicitly logged.
      * Each dispatch call runs with `--cd <empty scratch dir>` so an
        unsandboxed model has no path to ground_truth.json. The vision gate's
        trusted root stays the module constant (REAL_REPO_ROOT), not cwd.
  - Evidence-preserving execution:
      * `--format json` on dispatch so opencode's event stream (including tool
        events) is kept verbatim for contamination checks.
      * Only assistant FINAL text events are parsed as predictions.
      * A call is accepted only with returncode==0 AND dispatch status=="ok".
        No fallback parsing of a dispatch envelope/error as predictions.
      * Calls where the model invoked any tool are flagged contaminated and
        excluded from accuracy (unsandboxed harness cannot prove isolation).
  - Scoring:
      * Every call is scored on ITS OWN task field IDs only.
      * images and pdf scopes are scored separately on disjoint denominators;
        the PDF scope never inherits image fields.
      * Safe execution: argv lists, overwrite guard, raw stdout/stderr/latency
        persisted per call, quota_attempts vs inference_success distinguished.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from bench.vision.score import (
        detect_tool_events,
        parse_json_response,
        score_predictions,
        strict_json_loads,
    )
except ImportError:
    from score import (  # type: ignore[no-redef]
        detect_tool_events,
        parse_json_response,
        score_predictions,
        strict_json_loads,
    )


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_BENCH_DIR = REPO_ROOT / "bench" / "vision" / "synthetic"
DEFAULT_GT_PATH = DEFAULT_BENCH_DIR / "ground_truth.json"
DEFAULT_MANIFEST_PATH = DEFAULT_BENCH_DIR / "manifest.json"

MODEL_DEFAULT_EFFORT = {
    "deepseek-v4.1-flash": "high",
    "glm-5.3-flash": "max",
}

# Dispatch kills the vendor at --timeout; the runner wrapper must allow the
# dispatch process itself to finish writing diagnostics before killing it.
WRAPPER_GRACE_SECONDS = 120

PDF_DOCUMENTS = ("page_05_multipage_p1.png", "page_06_multipage_p2.png")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Prompt Hygiene & Answer Leak Sanitization
# ---------------------------------------------------------------------------

def sanitize_field_name(name: str, value: Any = None) -> str:
    """Sanitize field name to prevent any answer leaks from being passed to the model."""
    cleaned = name

    # Remove phrases like 'chứa O0l1586B', 'chứa 8568'
    cleaned = re.sub(r"(?i)\s*\(?chứa\s+[A-Za-z0-9_.-]+\)?", "", cleaned)

    # If the ground truth value is explicitly in the name, strip it
    if value is not None:
        str_val = str(value).strip()
        if len(str_val) >= 3 and str_val in cleaned:
            cleaned = cleaned.replace(str_val, "").strip()

    # Clean up double spaces or dangling punctuation
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def build_prompt_for_fields(
    document_name: str,
    fields: list[dict[str, Any]],
) -> str:
    """Construct model extraction prompt for the listed fields.

    STRICT PROHIBITION:
      NO 'value' or 'numeric_value' may ever be included in the prompt.

    Table-cell fields (any field carrying 'row' or 'column') are addressed
    ONLY by id/type/row/column. Their 'name' is dropped entirely: in real
    runs a table label like "Doanh thu bán hàng & dịch vụ Quý 2/2026" is the
    ground-truth answer of an adjacent text cell, so echoing it would leak
    the answer to a different field (cross-field leak). Non-table fields keep
    a descriptive name, scrubbed of their own ground-truth value.
    """
    field_specs = []
    for f in fields:
        spec: dict[str, Any] = {
            "id": f["id"],
            "type": f.get("type", "text"),
        }
        is_table_cell = "row" in f or "column" in f
        if not is_table_cell:
            spec["name"] = sanitize_field_name(f.get("name", ""), f.get("value"))
        if "row" in f:
            spec["row"] = f["row"]
        if "column" in f:
            spec["column"] = f["column"]
        field_specs.append(spec)

    prompt_lines = [
        "Bạn là trợ lý trích xuất dữ liệu hình ảnh và tài liệu quang học chuyên nghiệp.",
        f"Hãy quan sát kỹ tài liệu đính kèm ({document_name}) và trích xuất chính xác các trường sau:",
        "",
        "DANH SÁCH TRƯỜNG CẦN TRÍCH XUẤT:",
        json.dumps(field_specs, ensure_ascii=False, indent=2),
        "",
        "QUY TẮC BẮT BUỘC:",
        "1. CHỈ trích xuất thông tin nhìn thấy được trên ảnh/tài liệu đính kèm.",
        "2. TUYỆT ĐỐI KHÔNG sử dụng công cụ (tool), không duyệt workspace, không đọc file mã nguồn hay file ground truth.",
        "3. Trả về DUY NHẤT một JSON object hợp lệ ánh xạ từng trường 'id' sang giá trị tương ứng ('id': 'giá trị').",
        "4. Không giải thích, không thêm ghi chú, không dùng định dạng ngoài JSON object.",
        "",
        "Ví dụ cấu trúc trả về:",
        '{"trường_id_1": "giá trị 1", "trường_id_2": "giá trị 2"}',
    ]

    return "\n".join(prompt_lines)


# ---------------------------------------------------------------------------
# Runner Execution
# ---------------------------------------------------------------------------

def run_dispatch_call(
    cmd_args: list[str],
    timeout: int = 600,
    dry_run: bool = False,
    wrapper_grace: int = WRAPPER_GRACE_SECONDS,
) -> tuple[int, str, str, float]:
    """Execute bin/dispatch.py with safe argv list and measure latency.

    `timeout` is the per-vendor budget passed to dispatch. The wrapper waits
    `timeout + wrapper_grace` so the dispatch process can write its own timeout
    diagnostics first — exactly one actor kills the vendor, no competing kills.

    Returns: (returncode, stdout, stderr, latency_seconds)
    """
    if dry_run:
        return 0, '{"dry_run": true}', "", 0.001

    wrapper_timeout = timeout + wrapper_grace
    start_t = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=wrapper_timeout,
            shell=False,  # Safe argv execution (no shell interpolation)
        )
        latency = time.perf_counter() - start_t
        return proc.returncode, proc.stdout, proc.stderr, latency
    except subprocess.TimeoutExpired as e:
        latency = time.perf_counter() - start_t
        stdout = e.stdout.decode("utf-8", errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        stderr += (
            f"\n[runner] Wrapper timed out after {wrapper_timeout}s "
            f"(dispatch budget {timeout}s + {wrapper_grace}s grace)"
        )
        return 124, stdout, stderr, latency
    except Exception as e:
        latency = time.perf_counter() - start_t
        return 1, "", f"[runner] Subprocess error: {e}", latency


def _field_ids(fields: list[dict[str, Any]]) -> set[str]:
    return {f["id"] for f in fields if "id" in f}


def _condense(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "correct_fields": report["correct_fields"],
        "total_fields": report["total_fields"],
        "accuracy_percent": report["accuracy_percent"],
    }


def _merge_scope_reports(
    reports: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Additively merge scope reports (images + pdf) for mode=all.

    Each scope keeps its own denominator, so a field measured both as a single
    image page and inside the multipage PDF is counted once per presentation.
    Predictions are never merged across scopes (no id collision bias).
    """
    total_fields = 0
    correct_fields = 0
    by_document: dict[str, dict[str, Any]] = {}
    by_type: dict[str, dict[str, Any]] = {}
    fields: list[dict[str, Any]] = []

    for scope, report in reports.items():
        total_fields += report["total_fields"]
        correct_fields += report["correct_fields"]
        for bucket_name, bucket in (("by_document", by_document), ("by_type", by_type)):
            for key, stats in report[bucket_name].items():
                slot = bucket.setdefault(key, {"correct": 0, "total": 0})
                slot["correct"] += stats["correct"]
                slot["total"] += stats["total"]
        for record in report.get("fields", []):
            annotated = dict(record)
            annotated["scope"] = scope
            fields.append(annotated)

    for bucket in (by_document, by_type):
        for slot in bucket.values():
            slot["percent"] = (
                round(slot["correct"] / slot["total"] * 100.0, 2) if slot["total"] else 0.0
            )

    pct = (correct_fields / total_fields * 100.0) if total_fields else 0.0
    return {
        "evaluation_type": "deterministic_typed_accuracy",
        "scope": "combined",
        "note": (
            "Additive merge of images and pdf scopes. Fields of page_05/page_06 are "
            "counted once per input presentation (individual PNG and multipage PDF)."
        ),
        "scope_field_ids": None,
        "total_fields": total_fields,
        "correct_fields": correct_fields,
        "accuracy_percent": round(pct, 2),
        "by_document": by_document,
        "by_type": by_type,
        "fields": fields,
    }


def execute_benchmark(
    ground_truth_path: Path,
    bench_dir: Path,
    model: str,
    effort: str,
    mode: str,
    output_dir: Path,
    timeout: int = 600,
    overwrite: bool = False,
    dry_run: bool = False,
    dispatch_format: str = "json",
    wrapper_grace: int = WRAPPER_GRACE_SECONDS,
) -> dict[str, Any]:
    """Orchestrate vision benchmark run across selected files."""
    if output_dir.exists() and not overwrite:
        raise FileExistsError(
            f"Output directory '{output_dir}' already exists. "
            "Use --overwrite to allow replacing existing outputs."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_calls_dir = output_dir / "raw_calls"
    raw_calls_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir = output_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    scratch_root = output_dir / "scratch"

    # Explicitly log the unsandboxed harness limitation
    harness_warning = (
        "[CẢNH BÁO / NOTICE] Harness runs unsandboxed. "
        "Prompt-only restriction ('do not read workspace') is NOT strong security proof; "
        "an unconfined model could technically access workspace files if capable. "
        "Each call runs with --cd into an empty scratch dir and --format json is kept "
        "for tool-event detection; calls that used tools are excluded from accuracy. "
        "Results must be interpreted with this architectural boundary in mind."
    )
    sys.stderr.write(f"\n{harness_warning}\n\n")

    with open(ground_truth_path, encoding="utf-8") as f:
        gt_data = json.load(f)

    all_fields = gt_data.get("fields", [])

    # Group ground truth fields by document
    fields_by_doc: dict[str, list[dict[str, Any]]] = {}
    for f in all_fields:
        doc = f.get("document", "unknown")
        fields_by_doc.setdefault(doc, []).append(f)

    # Determine files to process based on mode
    target_tasks: list[dict[str, Any]] = []

    if mode in ("images", "all"):
        for doc_name, doc_fields in sorted(fields_by_doc.items()):
            if doc_name.endswith(".png"):
                file_path = bench_dir / doc_name
                target_tasks.append({
                    "task_id": doc_name.replace(".png", ""),
                    "document": doc_name,
                    "file_path": file_path,
                    "fields": doc_fields,
                    "scope": "images",
                    "is_pdf": False,
                })

    if mode in ("pdf", "all"):
        pdf_name = "multipage_contract.pdf"
        pdf_path = bench_dir / pdf_name
        # The PDF contains page 5 and page 6
        pdf_fields = [f for f in all_fields if f.get("document") in PDF_DOCUMENTS]
        target_tasks.append({
            "task_id": "multipage_contract_pdf",
            "document": pdf_name,
            "file_path": pdf_path,
            "fields": pdf_fields,
            "scope": "pdf",
            "is_pdf": True,
        })

    # Scope membership (which GT fields each mode actually put to the model).
    scope_field_ids: dict[str, set[str]] = {}
    for task in target_tasks:
        scope_field_ids.setdefault(task["scope"], set()).update(_field_ids(task["fields"]))

    quota_attempts = 0
    inference_success = 0
    contaminated_calls: list[dict[str, Any]] = []
    predictions_by_scope: dict[str, dict[str, Any]] = {"images": {}, "pdf": {}}
    call_records: list[dict[str, Any]] = []

    dispatch_script = REPO_ROOT / "bin" / "dispatch.py"

    for idx, task in enumerate(target_tasks, start=1):
        task_id = task["task_id"]
        doc_name = task["document"]
        file_path = task["file_path"]
        task_fields = task["fields"]
        task_field_ids = _field_ids(task_fields)

        prompt_text = build_prompt_for_fields(doc_name, task_fields)
        prompt_file = prompts_dir / f"prompt_{task_id}.txt"
        with open(prompt_file, "w", encoding="utf-8") as pf:
            pf.write(prompt_text)

        # Empty scratch cwd: an unsandboxed model starts with no workspace
        # containing ground truth. The vision gate's trusted root is a module
        # constant (REAL_REPO_ROOT), so --cd cannot widen or move it.
        call_cwd = scratch_root / task_id
        call_cwd.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            str(dispatch_script),
            "opencode",
            "--model", model,
            "--effort", effort,
            "--data-class", "code-nopii",
            "--synthetic-vision",
            "--file", str(file_path),
            "--timeout", str(timeout),
            "--format", dispatch_format,
            "--cd", str(call_cwd),
            "--result-json",
            "--prompt-file", str(prompt_file),
        ]

        sys.stderr.write(f"[{idx}/{len(target_tasks)}] Dispatching {doc_name} to {model} (effort={effort})...\n")

        quota_attempts += 1
        retcode, stdout, stderr, latency = run_dispatch_call(
            cmd, timeout=timeout, dry_run=dry_run, wrapper_grace=wrapper_grace
        )

        # --- Strict acceptance: retcode==0 AND dispatch status=="ok" ---------
        # No fallback: a dispatch envelope, an error payload, or stray prose is
        # never parsed as predictions. Unaccepted calls simply score 0 on their
        # own task fields (never excluded from the denominator).
        dispatch_obj: dict[str, Any] | None = None
        model_stdout = ""
        parsed_predictions: dict[str, Any] | None = None
        contaminated = False
        status = "failed"

        if dry_run:
            status = "dry_run"
        elif retcode != 0:
            status = f"exit_{retcode}"
        else:
            try:
                loaded = strict_json_loads(stdout)
            except Exception:
                loaded = None
            if not isinstance(loaded, dict):
                status = "invalid_dispatch_envelope"
            else:
                dispatch_obj = loaded
                if dispatch_obj.get("status") != "ok":
                    status = f"dispatch_{dispatch_obj.get('status', 'unknown')}"
                else:
                    model_stdout = dispatch_obj.get("stdout") or ""
                    contaminated = detect_tool_events(model_stdout)
                    raw_predictions = parse_json_response(model_stdout)
                    filtered: dict[str, Any] = {}
                    if raw_predictions is not None:
                        # Only the fields this task asked for are ever persisted.
                        filtered = {
                            k: v for k, v in raw_predictions.items() if k in task_field_ids
                        }
                        parsed_predictions = filtered or None
                    if contaminated:
                        # Tool use = unsandboxed contamination: keep whatever
                        # evidence there is (often none — tool_result payloads
                        # are not answers), never count it as vision accuracy.
                        status = "contaminated_tools"
                    elif raw_predictions is None:
                        status = "json_parse_failed"
                    elif not filtered:
                        status = "no_task_fields"
                    else:
                        status = "ok"
                        inference_success += 1
                        predictions_by_scope[task["scope"]].update(filtered)

        if contaminated or status == "contaminated_tools":
            contaminated_calls.append({
                "call_index": idx,
                "task_id": task_id,
                "scope": task["scope"],
                "status": status,
            })

        # Per-call score over THIS task's fields only.
        call_score = score_predictions(
            gt_data,
            parsed_predictions if (parsed_predictions and status == "ok") else {},
            field_ids=task_field_ids,
        )

        call_record: dict[str, Any] = {
            "call_index": idx,
            "task_id": task_id,
            "document": doc_name,
            "scope": task["scope"],
            "file_path": str(file_path),
            "workdir": str(call_cwd),
            "command": cmd,
            "latency_seconds": round(latency, 4),
            "returncode": retcode,
            "status": status,
            "contaminated": contaminated,
            "contamination_status": status if contaminated else None,
            "dispatch_status": (dispatch_obj or {}).get("status"),
            "field_ids": sorted(task_field_ids),
            "score": call_score,
            "raw_stdout": stdout,
            "raw_stderr": stderr,
            "model_stdout": model_stdout,
            "parsed_predictions": parsed_predictions,
            "timestamp": _utc_now(),
        }

        # Persist raw call result immediately
        raw_call_file = raw_calls_dir / f"call_{idx:02d}_{task_id}.json"
        with open(raw_call_file, "w", encoding="utf-8") as rf:
            json.dump(call_record, rf, ensure_ascii=False, indent=2)

        call_records.append(call_record)

    # --- Scope scoring: disjoint denominators, never full GT by accident -----
    scope_reports: dict[str, dict[str, Any]] = {}
    for scope in ("images", "pdf"):
        if scope in scope_field_ids:
            scope_reports[scope] = score_predictions(
                gt_data,
                predictions_by_scope[scope],
                field_ids=scope_field_ids[scope],
            )

    if mode == "all":
        primary_report = _merge_scope_reports(scope_reports)
    else:
        primary_report = scope_reports[mode]

    scoring_summary = {
        "primary_mode": mode,
        "images": _condense(scope_reports.get("images")),
        "pdf": _condense(scope_reports.get("pdf")),
        "images_applicable": "images" in scope_reports,
        "pdf_applicable": "pdf" in scope_reports,
        "images_field_count": len(scope_field_ids.get("images", set())),
        "pdf_field_count": len(scope_field_ids.get("pdf", set())),
        "excluded_contaminated_calls": [c["task_id"] for c in contaminated_calls],
        "note": (
            "images and pdf are scored on disjoint field sets; the primary figure "
            "follows --mode (mode=all = additive merge of both scopes)."
        ),
    }

    run_summary: dict[str, Any] = {
        "benchmark_metadata": {
            "model": model,
            "effort": effort,
            "mode": mode,
            "ground_truth_path": str(ground_truth_path),
            "total_tasks": len(target_tasks),
            "timeout_seconds": timeout,
            "wrapper_timeout_seconds": timeout + wrapper_grace,
            "dispatch_format": dispatch_format,
            "dry_run": dry_run,
            "timestamp": _utc_now(),
            "unsandboxed_warning": harness_warning,
        },
        "metrics": {
            "quota_attempts": quota_attempts,
            "inference_success": inference_success,
            "inference_success_rate": round(
                (inference_success / quota_attempts * 100.0) if quota_attempts > 0 else 0.0,
                2,
            ),
            "contaminated_calls": len(contaminated_calls),
            "note": "actual provider billing usage unknown; quota_attempts reflects dispatch calls made",
        },
        "summary": scoring_summary,
        "scope_reports": scope_reports,
        "score_report": primary_report,
        "calls": call_records,
    }

    summary_file = output_dir / "run_summary.json"
    with open(summary_file, "w", encoding="utf-8") as sf:
        json.dump(run_summary, sf, ensure_ascii=False, indent=2)

    sys.stderr.write(f"\nBenchmark completed. Summary written to: {summary_file}\n")
    return run_summary


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Synthetic vision benchmark runner.")
    parser.add_argument(
        "--model", "-m",
        default="deepseek-v4.1-flash",
        help="Model to benchmark (e.g. deepseek-v4.1-flash, glm-5.3-flash)",
    )
    parser.add_argument(
        "--effort",
        help="Reasoning effort (default: high for DeepSeek, max for GLM)",
    )
    parser.add_argument(
        "--mode",
        choices=["images", "pdf", "all"],
        default="images",
        help="Benchmark mode: images (6 PNGs), pdf (2-page multipage), or all",
    )
    parser.add_argument(
        "--ground-truth",
        default=str(DEFAULT_GT_PATH),
        help=f"Path to ground_truth.json (default: {DEFAULT_GT_PATH})",
    )
    parser.add_argument(
        "--bench-dir",
        default=str(DEFAULT_BENCH_DIR),
        help=f"Directory with synthetic images (default: {DEFAULT_BENCH_DIR})",
    )
    parser.add_argument(
        "--output-dir", "-o",
        help="Directory to save run results (default: bench/vision/results/<timestamp>_<model>)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting target output directory if it exists",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Per-call vendor timeout in seconds passed to dispatch (default: 600). "
             "The runner wrapper waits timeout+120s so dispatch can write diagnostics first.",
    )
    parser.add_argument(
        "--dispatch-format",
        choices=["text", "json"],
        default="json",
        help="Output format passed to dispatch (default: json — keeps opencode "
             "event stream so tool use/contamination is observable)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build prompts and simulate execution without invoking live network dispatch",
    )

    args = parser.parse_args()

    gt_path = Path(args.ground_truth)
    if not gt_path.is_file():
        sys.stderr.write(f"Error: ground truth file not found: {gt_path}\n")
        return 1

    bench_dir = Path(args.bench_dir)
    if not bench_dir.is_dir():
        sys.stderr.write(f"Error: synthetic bench directory not found: {bench_dir}\n")
        return 1

    model = args.model
    effort = args.effort or MODEL_DEFAULT_EFFORT.get(model, "medium")

    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        sanitized_model = model.replace("/", "_").replace(":", "_")
        out_dir = REPO_ROOT / "bench" / "vision" / "results" / f"{ts}_{sanitized_model}_{args.mode}"

    try:
        summary = execute_benchmark(
            ground_truth_path=gt_path,
            bench_dir=bench_dir,
            model=model,
            effort=effort,
            mode=args.mode,
            output_dir=out_dir,
            timeout=args.timeout,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
            dispatch_format=args.dispatch_format,
        )
    except FileExistsError as e:
        sys.stderr.write(f"Error: {e}\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"Fatal execution error: {e}\n")
        return 1

    sr = summary["score_report"]
    ss = summary["summary"]
    print(f"\n=== Benchmark Run Result ({model} - mode={args.mode}) ===")
    print(f"Quota Attempts: {summary['metrics']['quota_attempts']}")
    print(f"Inference Success: {summary['metrics']['inference_success']} ({summary['metrics']['inference_success_rate']}%)")
    print(f"Contaminated (tool use, excluded): {summary['metrics']['contaminated_calls']}")

    def _line(label: str, stats: dict[str, Any] | None, applicable: bool) -> str:
        if not applicable or stats is None:
            return f"{label}: n/a (not part of mode={args.mode})"
        return (
            f"{label}: {stats['correct_fields']}/{stats['total_fields']} "
            f"({stats['accuracy_percent']}%)"
        )

    print(_line("Images", ss["images"], ss["images_applicable"]))
    print(_line("PDF", ss["pdf"], ss["pdf_applicable"]))
    print(f"Primary (mode={args.mode}): {sr['correct_fields']}/{sr['total_fields']} ({sr['accuracy_percent']}%)")
    print(f"Results stored at: {out_dir}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
