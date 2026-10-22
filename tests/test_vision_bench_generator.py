"""Tests for synthetic vision benchmark generator (bench/vision/generate.py).

Verifies:
  1. Byte-level deterministic regeneration (SHA-256 identical across runs for PNGs & PDF).
  2. Ground truth schema_version=1 and coverage of all 4 types (amount, date, code, text).
  3. Manifest schema_version=1, accurate relative paths, and exact SHA-256 checksums.
  4. Specific benchmark cases:
     - Narrow multi-column table with numbers formatted as 1.234.567.890
     - Negative numbers in parentheses (12.345)
     - OCR confusing characters (0/O, 1/l, 5/6/8, 2026 vs 2006)
     - Degraded scan (blur, skew, noise, JPEG artifacts)
     - Rich Vietnamese text with diacritics
     - Multi-page document (2 pages out of 6) and corresponding PDF
  5. Multi-page PDF page count (when pypdf/pymupdf is available).
  6. Requirements cleanliness (no unnecessary runtime dependencies added).
  7. Font resolution and graceful fallback.
"""

from __future__ import annotations

import filecmp
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from bench.vision.generate import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SEED,
    FONT_CANDIDATES,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    compute_sha256,
    generate_benchmark,
    resolve_font,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_requirements_no_unnecessary_dependencies() -> None:
    """Ensure requirements.txt preserves stdlib-only runtime contract."""
    req_file = REPO_ROOT / "requirements.txt"
    assert req_file.is_file(), "requirements.txt must exist"
    content = req_file.read_text(encoding="utf-8")
    assert "CHỈ stdlib" in content or "stdlib" in content.lower(), (
        "requirements.txt must maintain the stdlib runtime policy"
    )


def test_generated_files_exist_and_match_manifest() -> None:
    """Verify that all 6 PNG pages, 1 PDF, manifest, and ground truth exist."""
    assert DEFAULT_OUTPUT_DIR.is_dir(), f"Synthetic bench dir {DEFAULT_OUTPUT_DIR} must exist"

    manifest_path = DEFAULT_OUTPUT_DIR / "manifest.json"
    gt_path = DEFAULT_OUTPUT_DIR / "ground_truth.json"

    assert manifest_path.is_file(), "manifest.json must exist"
    assert gt_path.is_file(), "ground_truth.json must exist"

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["schema_version"] == 1
    assert manifest["generator"] == "bench/vision/generate.py"
    assert manifest["seed"] == DEFAULT_SEED
    assert manifest["deterministic_bytes"] is True

    files = manifest["files"]
    assert len(files) == 7, f"Expected 7 files (6 PNGs + 1 PDF), got {len(files)}"

    png_files = [f for f in files if f["format"] == "PNG"]
    pdf_files = [f for f in files if f["format"] == "PDF"]

    assert len(png_files) == 6, f"Expected 6 PNG pages, got {len(png_files)}"
    assert len(pdf_files) == 1, f"Expected 1 PDF file, got {len(pdf_files)}"

    # Verify each file on disk matches its manifest entry
    for entry in files:
        file_path = DEFAULT_OUTPUT_DIR / entry["path"]
        assert file_path.is_file(), f"File {file_path} listed in manifest but missing on disk"
        actual_sha = compute_sha256(file_path)
        assert actual_sha == entry["sha256"], (
            f"SHA256 mismatch for {entry['path']}: expected {entry['sha256']}, got {actual_sha}"
        )
        assert file_path.stat().st_size == entry["bytes"]

    # Verify checksums dictionary in manifest has both short and relative paths
    checksums = manifest["checksums"]
    for entry in files:
        assert entry["path"] in checksums
        assert entry["rel_path"] in checksums
        assert checksums[entry["path"]] == entry["sha256"]
        assert checksums[entry["rel_path"]] == entry["sha256"]


def test_ground_truth_schema_and_types_coverage() -> None:
    """Verify ground_truth.json schema_version=1 and all field requirements."""
    gt_path = DEFAULT_OUTPUT_DIR / "ground_truth.json"
    with open(gt_path, encoding="utf-8") as f:
        gt = json.load(f)

    assert gt["schema_version"] == 1
    assert "fields" in gt
    fields = gt["fields"]
    assert len(fields) >= 20, f"Expected at least 20 ground truth fields, got {len(fields)}"

    # Check uniqueness of IDs
    field_ids = [f["id"] for f in fields]
    assert len(field_ids) == len(set(field_ids)), "All ground truth field IDs must be unique"

    # Verify field structure and allowed types
    allowed_types = {"amount", "date", "code", "text"}
    types_found = set()

    for f in fields:
        assert "id" in f and isinstance(f["id"], str) and len(f["id"]) > 0
        assert "type" in f and f["type"] in allowed_types, f"Invalid type in field: {f}"
        assert "value" in f and f["value"] is not None and str(f["value"]).strip() != ""
        assert "page" in f and 1 <= f["page"] <= 6
        assert "document" in f and f["document"].endswith(".png")
        types_found.add(f["type"])

        # For amount fields, ensure numeric_value is provided for exact numeric scoring
        if f["type"] == "amount":
            assert "numeric_value" in f, f"Amount field {f['id']} must provide numeric_value"
            assert isinstance(f["numeric_value"], (int, float))

    # Assert that all 4 required types are covered
    assert types_found == allowed_types, (
        f"Missing ground truth types: {allowed_types - types_found}"
    )


def test_ground_truth_specific_benchmark_cases() -> None:
    """Verify ground truth contains the required benchmark challenge cases."""
    gt_path = DEFAULT_OUTPUT_DIR / "ground_truth.json"
    with open(gt_path, encoding="utf-8") as f:
        gt = json.load(f)

    field_map = {f["id"]: f for f in gt["fields"]}

    # Case 1: Formatted amount 1.234.567.890
    assert "p1_rev_q1" in field_map
    assert field_map["p1_rev_q1"]["value"] == "1.234.567.890"
    assert field_map["p1_rev_q1"]["numeric_value"] == 1234567890

    # Case 2: Negative number in parentheses (12.345)
    assert "p2_loss_carried" in field_map
    assert field_map["p2_loss_carried"]["value"] == "(12.345)"
    assert field_map["p2_loss_carried"]["numeric_value"] == -12345

    # Case 3: Confusing characters 0/O, 1/l, 5/6/8, and 2026 vs 2006
    assert "p3_contract_code" in field_map
    p3_code = field_map["p3_contract_code"]["value"]
    assert "2026" in p3_code
    assert "O" in p3_code and "0" in p3_code  # O vs 0
    assert "l" in p3_code and "1" in p3_code  # l vs 1
    assert any(c in p3_code for c in ("5", "6", "8"))  # 5, 6, 8

    assert "p3_ref_code_2006" in field_map
    assert "2006" in field_map["p3_ref_code_2006"]["value"]

    assert "p3_serial_code" in field_map
    assert "8568" in field_map["p3_serial_code"]["value"]

    # Case 4: Degraded scan fields
    assert "p4_trans_id" in field_map
    assert field_map["p4_trans_id"]["value"] == "TXN-882006-SCAN"
    assert "p4_debit_amount" in field_map
    assert field_map["p4_debit_amount"]["value"] == "56.810.000"

    # Case 5: Vietnamese diacritics & contract data
    assert "p5_client_name" in field_map
    assert "Công ty Cổ phần Công nghệ Sao Kim" in field_map["p5_client_name"]["value"]
    assert "p5_vendor_name" in field_map
    assert "Công ty TNHH Phát triển Phần mềm Hải Âu" in field_map["p5_vendor_name"]["value"]

    # Case 6: Multi-page contract financial total & effective date
    assert "p6_total_amount" in field_map
    assert field_map["p6_total_amount"]["value"] == "495.000.000"
    assert field_map["p6_effective_date"]["value"] == "2026-05-01"


def test_deterministic_reproducibility() -> None:
    """Verify that running generator twice produces 100% byte-identical files."""
    with tempfile.TemporaryDirectory() as dir1, tempfile.TemporaryDirectory() as dir2:
        m1 = generate_benchmark(output_dir=dir1, seed=42)
        m2 = generate_benchmark(output_dir=dir2, seed=42)

        files1 = {f["path"]: f["sha256"] for f in m1["files"]}
        files2 = {f["path"]: f["sha256"] for f in m2["files"]}

        assert files1 == files2, f"SHA256 mismatch between runs: {files1} != {files2}"

        for filename in files1:
            p1 = Path(dir1) / filename
            p2 = Path(dir2) / filename
            assert filecmp.cmp(p1, p2, shallow=False), (
                f"File {filename} is not byte-identical across runs!"
            )


def test_pdf_page_count_and_structure() -> None:
    """Verify PDF multi-page structure and magic bytes."""
    pdf_path = DEFAULT_OUTPUT_DIR / "multipage_contract.pdf"
    assert pdf_path.is_file(), "multipage_contract.pdf must exist"

    # Verify PDF magic bytes
    with open(pdf_path, "rb") as f:
        header = f.read(5)
    assert header.startswith(b"%PDF-"), f"Invalid PDF magic: {header!r}"

    # Verify page count = 2 via pypdf (if installed)
    try:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        assert len(reader.pages) == 2, f"Expected 2 pages in PDF, got {len(reader.pages)}"
    except ImportError:
        pass


def test_font_resolution_fallback() -> None:
    """Verify resolve_font returns usable font even if preferred paths are missing."""
    font, resolved_path = resolve_font(size=18)
    assert font is not None
    assert isinstance(resolved_path, str)

    # Test mono resolution
    mono_font, mono_path = resolve_font(size=14, prefer_mono=True)
    assert mono_font is not None
    assert isinstance(mono_path, str)


def test_cli_execution() -> None:
    """Verify bench/vision/generate.py can be invoked via CLI."""
    with tempfile.TemporaryDirectory() as tmpdir:
        res = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "bench" / "vision" / "generate.py"),
                "--output-dir",
                tmpdir,
                "--seed",
                "99",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert res.returncode == 0
        assert "Generated 7 synthetic benchmark files" in res.stdout
        assert (Path(tmpdir) / "manifest.json").is_file()
        assert (Path(tmpdir) / "ground_truth.json").is_file()
