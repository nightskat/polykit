#!/usr/bin/env python3
"""Synthetic vision benchmark document generator.

Generates 6 synthetic PNG pages and 1 multi-page PDF designed to test
tricky OCR / Vision LLM edge-cases in Vietnamese financial and business records:
  - Page 1: Narrow multi-column table with formatted numbers (e.g. 1.234.567.890)
  - Page 2: Negative numbers in parentheses (e.g. (12.345), (98.765.432))
  - Page 3: Confusing characters (0/O, 1/l, 5/6/8, 2026 vs 2006)
  - Page 4: Degraded scan (blur, skew, noise, JPEG artifacts)
  - Page 5: Vietnamese diacritics - Multi-page contract (Page 1/2)
  - Page 6: Vietnamese financial summary - Multi-page contract (Page 2/2)
  - Multi-page PDF: Combines Page 5 and Page 6 into a 2-page PDF

All data is 100% synthetic with zero real person names.
Output is byte-deterministic when given the same seed and system font.
Fixed PDF metadata timestamps ensure deterministic PDF hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

DEFAULT_SEED = 42
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "synthetic"
FIXED_PDF_TIME = time.gmtime(1700000000)  # Fixed epoch for deterministic PDF output

# Page dimensions (A4 @ 150 DPI)
PAGE_WIDTH = 1240
PAGE_HEIGHT = 1754

FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    # Windows
    "C:/Windows/Fonts/arial.ttf",
]

MONO_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/System/Library/Fonts/Supplemental/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "C:/Windows/Fonts/cour.ttf",
]


def resolve_font(
    size: int = 16,
    prefer_mono: bool = False,
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, str]:
    """Resolve an available system font with fallback.

    Returns the font object and the resolved font path/identifier.
    """
    candidates = MONO_FONT_CANDIDATES if prefer_mono else FONT_CANDIDATES
    for path_str in candidates:
        if os.path.isfile(path_str):
            try:
                font = ImageFont.truetype(path_str, size)
                # Quick test of Vietnamese diacritics
                _ = font.getmask("Hóa đơn GTGT số 01234 (12.345)")
                return font, path_str
            except Exception:
                continue

    # Fallback to general candidates if mono was preferred but failed
    if prefer_mono:
        for path_str in FONT_CANDIDATES:
            if os.path.isfile(path_str):
                try:
                    font = ImageFont.truetype(path_str, size)
                    _ = font.getmask("Hóa đơn GTGT số 01234 (12.345)")
                    return font, path_str
                except Exception:
                    continue

    # Final fallback: default PIL font
    try:
        return ImageFont.load_default(size=size), "PIL.default"
    except TypeError:
        return ImageFont.load_default(), "PIL.default"


def compute_sha256(file_path: Path) -> str:
    """Compute hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def draw_header_banner(
    draw: ImageDraw.ImageDraw,
    title: str,
    subtitle: str,
    font_title: ImageFont.ImageFont,
    font_sub: ImageFont.ImageFont,
    top_y: int = 60,
) -> int:
    """Draw a professional document header banner."""
    draw.text((80, top_y), title, fill=(20, 20, 20), font=font_title)
    draw.text((80, top_y + 40), subtitle, fill=(80, 80, 80), font=font_sub)
    draw.line([(80, top_y + 75), (PAGE_WIDTH - 80, top_y + 75)], fill=(180, 180, 180), width=2)
    return top_y + 95


# ==============================================================================
# Page 1: Narrow Multi-Column Table
# ==============================================================================
def render_page_1(font_path: str) -> tuple[Image.Image, list[dict[str, Any]]]:
    """Page 1: Narrow multi-column financial statement with numbers like 1.234.567.890."""
    im = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), color=(255, 255, 255))
    draw = ImageDraw.Draw(im)

    font_title, _ = resolve_font(26)
    font_sub, _ = resolve_font(18)
    font_header, _ = resolve_font(15)
    font_cell, _ = resolve_font(14)
    font_mono, _ = resolve_font(14, prefer_mono=True)

    y = draw_header_banner(
        draw,
        "CÔNG TY CP THƯƠNG MẠI SAO MAI (GIẢ LẬP)",
        "BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT - BẢNG CỘT HẸP",
        font_title,
        font_sub,
    )

    draw.text((80, y), "Kỳ kế toán kết thúc ngày: 30/06/2026", fill=(50, 50, 50), font=font_cell)
    draw.text((PAGE_WIDTH - 380, y), "Mã tài liệu: BCTC-2026-NARROW", fill=(50, 50, 50), font=font_mono)
    draw.text((80, y + 25), "Đơn vị tính: Đồng Việt Nam (VNĐ)", fill=(90, 90, 90), font=font_cell)
    y += 65

    # Columns: STT (50), Mã (80), Chỉ tiêu (340), TM (50), Quý 1 (170), Quý 2 (170), Lũy kế (220)
    cols = [
        ("STT", 60),
        ("Mã số", 90),
        ("Chỉ tiêu tài chính", 350),
        ("TM", 50),
        ("Quý 1/2026", 170),
        ("Quý 2/2026", 170),
        ("Lũy kế 2026", 190),
    ]
    table_x = 80
    row_height = 36

    # Draw table header background
    table_w = sum(w for _, w in cols)
    draw.rectangle([table_x, y, table_x + table_w, y + row_height], fill=(235, 240, 248), outline=(120, 140, 170))

    cur_x = table_x
    for name, w in cols:
        draw.text((cur_x + 8, y + 8), name, fill=(20, 40, 80), font=font_header)
        draw.line([(cur_x + w, y), (cur_x + w, y + row_height)], fill=(120, 140, 170), width=1)
        cur_x += w
    y += row_height

    rows = [
        ("01", "DT-01", "Doanh thu bán hàng & dịch vụ", "01", "1.234.567.890", "1.450.230.100", "2.684.797.990"),
        ("02", "GV-02", "Giá vốn hàng bán", "02", "890.123.456", "920.300.000", "1.810.423.456"),
        ("03", "LN-03", "Lợi nhuận gộp", "03", "344.444.434", "529.930.100", "874.374.534"),
        ("04", "TC-04", "Doanh thu tài chính", "04", "45.678.900", "67.890.120", "113.569.020"),
        ("05", "CP-05", "Chi phí tài chính", "05", "23.456.780", "34.567.890", "58.024.670"),
        ("06", "QL-06", "Chi phí quản lý doanh nghiệp", "06", "120.345.670", "145.678.900", "266.024.570"),
        ("07", "TT-07", "Tổng lợi nhuận trước thuế", "07", "246.320.884", "417.573.430", "663.894.314"),
        ("08", "TNDN-08", "Thuế TNDN hiện hành", "08", "49.264.177", "83.514.686", "132.778.863"),
        ("09", "ST-09", "Lợi nhuận sau thuế TNDN", "09", "197.056.707", "334.058.744", "531.115.451"),
        ("10", "KH-10", "Khấu hao tài sản cố định", "10", "35.120.000", "36.200.000", "71.320.000"),
        ("11", "PT-11", "Tiền thu từ bán hàng", "11", "1.180.500.000", "1.410.000.000", "2.590.500.000"),
        ("12", "CT-12", "Tiền chi trả người cung cấp", "12", "810.400.000", "895.000.000", "1.705.400.000"),
    ]

    for idx, row in enumerate(rows):
        bg = (255, 255, 255) if idx % 2 == 0 else (248, 250, 253)
        draw.rectangle([table_x, y, table_x + table_w, y + row_height], fill=bg, outline=(200, 210, 225))
        cur_x = table_x
        for col_idx, (val, (_, w)) in enumerate(zip(row, cols)):
            is_num = col_idx >= 4
            cell_font = font_mono if (is_num or col_idx in (0, 1, 3)) else font_cell
            draw.text((cur_x + 8, y + 8), val, fill=(20, 20, 20), font=cell_font)
            draw.line([(cur_x + w, y), (cur_x + w, y + row_height)], fill=(200, 210, 225), width=1)
            cur_x += w
        y += row_height

    # Footer note
    y += 30
    draw.text((80, y), "Ghi chú: Toàn bộ dữ liệu được lập trên cơ sở dồn tích giả định phục vụ kiểm chuẩn thị giác máy tính.", fill=(120, 120, 120), font=font_cell)

    fields = [
        {
            "id": "p1_rev_q1",
            "page": 1,
            "document": "page_01_narrow_table.png",
            "name": "Doanh thu bán hàng Quý 1",
            "type": "amount",
            "value": "1.234.567.890",
            "numeric_value": 1234567890,
        },
        {
            "id": "p1_cogs_q1",
            "page": 1,
            "document": "page_01_narrow_table.png",
            "name": "Giá vốn hàng bán Quý 1",
            "type": "amount",
            "value": "890.123.456",
            "numeric_value": 890123456,
        },
        {
            "id": "p1_gross_profit_q1",
            "page": 1,
            "document": "page_01_narrow_table.png",
            "name": "Lợi nhuận gộp Quý 1",
            "type": "amount",
            "value": "344.444.434",
            "numeric_value": 344444434,
        },
        {
            "id": "p1_period_date",
            "page": 1,
            "document": "page_01_narrow_table.png",
            "name": "Ngày kết thúc kỳ kế toán",
            "type": "date",
            "value": "2026-06-30",
        },
        {
            "id": "p1_report_code",
            "page": 1,
            "document": "page_01_narrow_table.png",
            "name": "Mã tài liệu báo cáo",
            "type": "code",
            "value": "BCTC-2026-NARROW",
        },
    ]
    return im, fields


# ==============================================================================
# Page 2: Negative Numbers in Parentheses
# ==============================================================================
def render_page_2(font_path: str) -> tuple[Image.Image, list[dict[str, Any]]]:
    """Page 2: Financial statement with negative numbers in parentheses: (12.345), (98.765.432)."""
    im = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), color=(255, 255, 255))
    draw = ImageDraw.Draw(im)

    font_title, _ = resolve_font(26)
    font_sub, _ = resolve_font(18)
    font_header, _ = resolve_font(15)
    font_cell, _ = resolve_font(14)
    font_mono, _ = resolve_font(14, prefer_mono=True)

    y = draw_header_banner(
        draw,
        "CÔNG TY CP ĐẦU TƯ BẮC HÀ (GIẢ LẬP)",
        "BẢNG CÂN ĐỐI TỔNG HỢP VÀ DỰ PHÒNG TỔN THẤT TÀI CHÍNH",
        font_title,
        font_sub,
    )

    draw.text((80, y), "Thời điểm lập báo cáo: 30/09/2026", fill=(50, 50, 50), font=font_cell)
    draw.text((PAGE_WIDTH - 360, y), "Mã đối chiếu: BC-AM-4212", fill=(50, 50, 50), font=font_mono)
    draw.text((80, y + 25), "Quy ước: Số âm được trình bày trong ngoặc đơn ( )", fill=(130, 40, 40), font=font_cell)
    y += 65

    cols = [
        ("Mã TK", 100),
        ("Khoản mục kế toán / Chỉ tiêu dự phòng", 450),
        ("Số đầu năm", 250),
        ("Số cuối Quý 3/2026", 280),
    ]
    table_x = 80
    row_height = 38
    table_w = sum(w for _, w in cols)

    draw.rectangle([table_x, y, table_x + table_w, y + row_height], fill=(244, 238, 238), outline=(180, 140, 140))
    cur_x = table_x
    for name, w in cols:
        draw.text((cur_x + 10, y + 10), name, fill=(90, 30, 30), font=font_header)
        draw.line([(cur_x + w, y), (cur_x + w, y + row_height)], fill=(180, 140, 140), width=1)
        cur_x += w
    y += row_height

    rows = [
        ("4212", "Lợi nhuận sau thuế chưa phân phối năm nay", "54.321.000", "(12.345)"),
        ("1113", "Lưu chuyển tiền thuần từ hoạt động kinh doanh", "120.000.000", "(98.765.432)"),
        ("2294", "Dự phòng tổn thất đầu tư tài chính dài hạn", "(5.000.000)", "(15.500.000)"),
        ("4190", "Cổ phiếu quỹ đang nắm giữ", "(25.000.000)", "(25.000.000)"),
        ("1319", "Dự phòng phải thu khó đòi ngắn hạn", "(8.400.000)", "(12.600.000)"),
        ("3341", "Phải trả công nhân viên còn tồn đọng", "15.200.000", "(4.320.000)"),
        ("4111", "Vốn góp của chủ sở hữu", "500.000.000", "500.000.000"),
        ("1111", "Tiền mặt tồn quỹ", "8.900.000", "2.150.000"),
        ("1121", "Tiền gửi ngân hàng không kỳ hạn", "45.000.000", "(1.250.000)"),
    ]

    for idx, row in enumerate(rows):
        bg = (255, 255, 255) if idx % 2 == 0 else (253, 249, 249)
        draw.rectangle([table_x, y, table_x + table_w, y + row_height], fill=bg, outline=(225, 205, 205))
        cur_x = table_x
        for col_idx, (val, (_, w)) in enumerate(zip(row, cols)):
            is_neg = "(" in val and ")" in val
            color = (180, 20, 20) if is_neg else (20, 20, 20)
            cell_font = font_mono if col_idx in (0, 2, 3) else font_cell
            draw.text((cur_x + 10, y + 10), val, fill=color, font=cell_font)
            draw.line([(cur_x + w, y), (cur_x + w, y + row_height)], fill=(225, 205, 205), width=1)
            cur_x += w
        y += row_height

    fields = [
        {
            "id": "p2_loss_carried",
            "page": 2,
            "document": "page_02_negative_numbers.png",
            "name": "Lợi nhuận sau thuế chưa phân phối (âm)",
            "type": "amount",
            "value": "(12.345)",
            "numeric_value": -12345,
        },
        {
            "id": "p2_cashflow_neg",
            "page": 2,
            "document": "page_02_negative_numbers.png",
            "name": "Lưu chuyển tiền thuần kinh doanh (âm)",
            "type": "amount",
            "value": "(98.765.432)",
            "numeric_value": -98765432,
        },
        {
            "id": "p2_reserve_neg",
            "page": 2,
            "document": "page_02_negative_numbers.png",
            "name": "Dự phòng tổn thất tài chính (âm)",
            "type": "amount",
            "value": "(15.500.000)",
            "numeric_value": -15500000,
        },
        {
            "id": "p2_balance_date",
            "page": 2,
            "document": "page_02_negative_numbers.png",
            "name": "Ngày báo cáo cân đối",
            "type": "date",
            "value": "2026-09-30",
        },
        {
            "id": "p2_report_code",
            "page": 2,
            "document": "page_02_negative_numbers.png",
            "name": "Mã tài liệu kế toán",
            "type": "code",
            "value": "BC-AM-4212",
        },
    ]
    return im, fields


# ==============================================================================
# Page 3: Confusing Characters (0/O, 1/l, 5/6/8, 2026 vs 2006)
# ==============================================================================
def render_page_3(font_path: str) -> tuple[Image.Image, list[dict[str, Any]]]:
    """Page 3: Test cases with characters that frequently confuse OCR/vision."""
    im = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), color=(255, 255, 255))
    draw = ImageDraw.Draw(im)

    font_title, _ = resolve_font(26)
    font_sub, _ = resolve_font(18)
    font_header, _ = resolve_font(16)
    font_cell, _ = resolve_font(15)
    font_mono, _ = resolve_font(16, prefer_mono=True)

    y = draw_header_banner(
        draw,
        "TRUNG TÂM ĐỐI SOÁT DỮ LIỆU ĐIỆN TỬ (GIẢ LẬP)",
        "BIÊN BẢN ĐỐI SOÁT MÃ HỒ SƠ - BÀI TEST KÝ TỰ DỄ NHẦM LẪN",
        font_title,
        font_sub,
    )

    draw.text((80, y), "Ngày lập biên bản đối soát: 15/01/2026", fill=(50, 50, 50), font=font_cell)
    draw.text((PAGE_WIDTH - 420, y), "Mục tiêu: Đánh giá phân biệt 0/O 1/l 5/6/8 2026/2006", fill=(100, 100, 100), font=font_cell)
    y += 50

    # Draw informative section boxes
    items = [
        ("Mã hợp đồng điện tử mới (năm 2026):", "HD-2026-O0l1586B", "Chứa O hoa, 0 số, l thường, 1 số, 5, 8, 6, B hoa"),
        ("Mã tham chiếu hồ sơ cũ (năm 2006):", "REF-2006-0Ol1", "So sánh đối lập trực tiếp năm 2006 với 2026"),
        ("Số xê-ri thiết bị kiểm định:", "SERIES-8568-2006", "Tổ hợp số 8, 5, 6, 8 và mốc 2006"),
        ("Mã chứng từ phụ thuộc:", "VOUCHER-1l0O-2026", "Tổ hợp 1 số, l thường, 0 số, O hoa"),
        ("Số tiền phí đối soát dịch vụ:", "8.568.015 VNĐ", "Bộ số 8, 5, 6, 8, 0, 1, 5"),
    ]

    for label, code_val, note in items:
        draw.rectangle([80, y, PAGE_WIDTH - 80, y + 90], fill=(250, 250, 252), outline=(210, 215, 230))
        draw.text((100, y + 15), label, fill=(50, 50, 70), font=font_cell)
        draw.text((100, y + 45), code_val, fill=(10, 20, 60), font=font_mono)
        draw.text((PAGE_WIDTH - 500, y + 45), f"({note})", fill=(120, 120, 140), font=font_cell)
        y += 110

    # Add explanatory table
    draw.text((80, y), "Bảng chi tiết phân tích lỗi quang học thường gặp:", fill=(30, 30, 30), font=font_header)
    y += 35

    draw.rectangle([80, y, PAGE_WIDTH - 80, y + 160], fill=(255, 255, 255), outline=(180, 180, 180))
    draw.text((100, y + 15), "1. Phân biệt chữ O hoa (ASCII 79) và số 0 (ASCII 48): Cặp O0 trong 'HD-2026-O0l1586B'", fill=(40, 40, 40), font=font_cell)
    draw.text((100, y + 45), "2. Phân biệt chữ l thường (ASCII 108) và số 1 (ASCII 49): Cặp l1 trong 'HD-2026-O0l1586B'", fill=(40, 40, 40), font=font_cell)
    draw.text((100, y + 75), "3. Phân biệt các số cong khép kín 5, 6, 8: Chuỗi 586 và 8568", fill=(40, 40, 40), font=font_cell)
    draw.text((100, y + 105), "4. Phân biệt năm tài chính 2026 và 2006 trong cùng ngữ cảnh hồ sơ lưu chuyển", fill=(40, 40, 40), font=font_cell)
    draw.text((100, y + 135), "5. Dữ liệu đối soát hoàn toàn được sinh ngẫu nhiên có kiểm soát (deterministic)", fill=(100, 100, 100), font=font_cell)

    fields = [
        {
            "id": "p3_contract_code",
            "page": 3,
            "document": "page_03_confusing_chars.png",
            "name": "Mã hợp đồng chứa O0l1586B",
            "type": "code",
            "value": "HD-2026-O0l1586B",
        },
        {
            "id": "p3_ref_code_2006",
            "page": 3,
            "document": "page_03_confusing_chars.png",
            "name": "Mã tham chiếu hồ sơ năm 2006",
            "type": "code",
            "value": "REF-2006-0Ol1",
        },
        {
            "id": "p3_serial_code",
            "page": 3,
            "document": "page_03_confusing_chars.png",
            "name": "Số xê-ri thiết bị chứa 8568",
            "type": "code",
            "value": "SERIES-8568-2006",
        },
        {
            "id": "p3_reconciliation_date",
            "page": 3,
            "document": "page_03_confusing_chars.png",
            "name": "Ngày đối soát biên bản",
            "type": "date",
            "value": "2026-01-15",
        },
        {
            "id": "p3_fee_amount",
            "page": 3,
            "document": "page_03_confusing_chars.png",
            "name": "Số tiền phí đối soát dịch vụ",
            "type": "amount",
            "value": "8.568.015",
            "numeric_value": 8568015,
        },
    ]
    return im, fields


# ==============================================================================
# Page 4: Degraded Scan (Blur, Skew, Noise, JPEG Artifacts)
# ==============================================================================
def render_page_4(font_path: str, seed: int = DEFAULT_SEED) -> tuple[Image.Image, list[dict[str, Any]]]:
    """Page 4: Simulates a degraded scan (blur, skew rotation, noise, JPEG artifacts)."""
    # Create base receipt on slightly off-white paper
    im = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), color=(250, 248, 244))
    draw = ImageDraw.Draw(im)

    font_title, _ = resolve_font(25)
    font_sub, _ = resolve_font(18)
    font_bold, _ = resolve_font(16)
    font_cell, _ = resolve_font(15)
    font_mono, _ = resolve_font(16, prefer_mono=True)

    y = draw_header_banner(
        draw,
        "NGÂN HÀNG THƯƠNG MẠI GIẢ LẬP VIỆT NAM",
        "ỦY NHIỆM CHI / GIẤY BÁO NỢ (BẢN SCAN LƯU TRỮ CHỨNG TỪ)",
        font_title,
        font_sub,
    )

    draw.text((80, y), "Mã chứng từ giao dịch:", fill=(40, 40, 40), font=font_cell)
    draw.text((320, y), "TXN-882006-SCAN", fill=(10, 10, 10), font=font_mono)
    y += 35

    draw.text((80, y), "Ngày hạch toán hệ thống:", fill=(40, 40, 40), font=font_cell)
    draw.text((320, y), "12/03/2026", fill=(10, 10, 10), font=font_mono)
    y += 35

    draw.text((80, y), "Tài khoản trích nợ:", fill=(40, 40, 40), font=font_cell)
    draw.text((320, y), "01234567890 (VND)", fill=(10, 10, 10), font=font_mono)
    y += 35

    draw.text((80, y), "Số tiền ghi nợ thực tế:", fill=(40, 40, 40), font=font_cell)
    draw.text((320, y), "56.810.000 VNĐ", fill=(10, 10, 10), font=font_bold)
    y += 35

    draw.text((80, y), "Bằng chữ:", fill=(40, 40, 40), font=font_cell)
    draw.text((320, y), "Năm mươi sáu triệu tám trăm mười nghìn đồng chẵn", fill=(40, 40, 40), font=font_cell)
    y += 35

    draw.text((80, y), "Nội dung giao dịch:", fill=(40, 40, 40), font=font_cell)
    draw.text((320, y), "Phí bảo lãnh thanh toán hợp đồng", fill=(10, 10, 10), font=font_bold)
    y += 60

    # Draw receipt border box
    draw.rectangle([80, y, PAGE_WIDTH - 80, y + 220], outline=(150, 150, 150), width=2)
    draw.text((100, y + 20), "Đơn vị thụ hưởng: CÔNG TY TNHH PHẦN MỀM THÁI BÌNH DƯƠNG", fill=(30, 30, 30), font=font_bold)
    draw.text((100, y + 60), "Tài khoản nhận: 9876543210 - Ngân hàng TMCP Ngoại Thương", fill=(50, 50, 50), font=font_cell)
    draw.text((100, y + 100), "Trạng thái: GIAO DỊCH ĐÃ ĐƯỢC XÁC THỰC THÀNH CÔNG", fill=(20, 100, 40), font=font_bold)
    draw.text((100, y + 140), "Chữ ký kiểm soát viên: ĐÃ KÝ ĐIỆN TỬ (MÃ AUTH-7719-OK)", fill=(80, 80, 80), font=font_cell)
    draw.text((100, y + 180), "Lưu ý lưu kho: Bản scan đã qua nén ảnh số chất lượng thấp", fill=(120, 120, 120), font=font_cell)

    # 1. Deterministic noise (speckles)
    rng = random.Random(seed)
    for _ in range(25000):
        px = rng.randint(0, PAGE_WIDTH - 1)
        py = rng.randint(0, PAGE_HEIGHT - 1)
        gray = rng.randint(160, 225)
        draw.point((px, py), fill=(gray, gray, gray))

    # 2. Skew / Rotation (subtle scan angle, e.g. 0.8 degrees)
    im = im.rotate(0.8, resample=Image.Resampling.BICUBIC, fillcolor=(250, 248, 244))

    # 3. Gaussian Blur (slight optical blur)
    im = im.filter(ImageFilter.GaussianBlur(radius=0.9))

    # 4. JPEG Artifacts (save to memory with quality=26 and reload)
    bio = io.BytesIO()
    im.save(bio, format="JPEG", quality=26)
    bio.seek(0)
    im = Image.open(bio).convert("RGB")

    fields = [
        {
            "id": "p4_trans_id",
            "page": 4,
            "document": "page_04_degraded_scan.png",
            "name": "Mã giao dịch ngân hàng scan",
            "type": "code",
            "value": "TXN-882006-SCAN",
        },
        {
            "id": "p4_posting_date",
            "page": 4,
            "document": "page_04_degraded_scan.png",
            "name": "Ngày hạch toán giao dịch",
            "type": "date",
            "value": "2026-03-12",
        },
        {
            "id": "p4_debit_amount",
            "page": 4,
            "document": "page_04_degraded_scan.png",
            "name": "Số tiền ghi nợ",
            "type": "amount",
            "value": "56.810.000",
            "numeric_value": 56810000,
        },
        {
            "id": "p4_description",
            "page": 4,
            "document": "page_04_degraded_scan.png",
            "name": "Nội dung giao dịch bảo lãnh",
            "type": "text",
            "value": "Phí bảo lãnh thanh toán hợp đồng",
        },
    ]
    return im, fields


# ==============================================================================
# Page 5: Multi-page Contract (Page 1/2) - Vietnamese Diacritics
# ==============================================================================
def render_page_5(font_path: str) -> tuple[Image.Image, list[dict[str, Any]]]:
    """Page 5: Page 1 of a multi-page Vietnamese contract with rich diacritics."""
    im = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), color=(255, 255, 255))
    draw = ImageDraw.Draw(im)

    font_national, _ = resolve_font(20)
    font_motto, _ = resolve_font(17)
    font_title, _ = resolve_font(22)
    font_bold, _ = resolve_font(16)
    font_body, _ = resolve_font(15)
    font_mono, _ = resolve_font(15, prefer_mono=True)

    y = 60
    # National motto header (centered)
    draw.text((PAGE_WIDTH // 2 - 240, y), "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", fill=(10, 10, 10), font=font_national)
    y += 32
    draw.text((PAGE_WIDTH // 2 - 140, y), "Độc lập - Tự do - Hạnh phúc", fill=(20, 20, 20), font=font_motto)
    y += 28
    draw.line([(PAGE_WIDTH // 2 - 120, y), (PAGE_WIDTH // 2 + 120, y)], fill=(80, 80, 80), width=2)
    y += 45

    # Contract Title
    draw.text((PAGE_WIDTH // 2 - 270, y), "HỢP ĐỒNG DỊCH VỤ CÔNG NGHỆ THÔNG TIN", fill=(10, 30, 80), font=font_title)
    y += 35
    draw.text((PAGE_WIDTH // 2 - 130, y), "Số: HĐ-2026/SK-HA/01", fill=(60, 60, 60), font=font_mono)
    y += 45

    draw.text((100, y), "- Căn cứ Bộ luật Dân sự nước Cộng hòa Xã hội Chủ nghĩa Việt Nam năm 2015;", fill=(60, 60, 60), font=font_body)
    y += 28
    draw.text((100, y), "- Căn cứ Luật Thương mại và nhu cầu thực tế của hai bên thỏa thuận;", fill=(60, 60, 60), font=font_body)
    y += 40

    draw.text((100, y), "Hôm nay, ngày 18 tháng 04 năm 2026, chúng tôi gồm có:", fill=(30, 30, 30), font=font_body)
    y += 40

    # Party A
    draw.text((100, y), "BÊN A (BÊN SỬ DỤNG DỊCH VỤ):", fill=(10, 30, 80), font=font_bold)
    y += 30
    draw.text((120, y), "Tên đơn vị: Công ty Cổ phần Công nghệ Sao Kim", fill=(20, 20, 20), font=font_bold)
    y += 28
    draw.text((120, y), "Địa chỉ: Tầng 5, Tòa nhà Công nghệ Giả Lập, Quận 1, TP. Hồ Chí Minh", fill=(40, 40, 40), font=font_body)
    y += 28
    draw.text((120, y), "Mã số thuế: 0312987654 - Điện thoại: (028) 3822 0000", fill=(40, 40, 40), font=font_body)
    y += 45

    # Party B
    draw.text((100, y), "BÊN B (BÊN CUNG CẤP DỊCH VỤ):", fill=(10, 30, 80), font=font_bold)
    y += 30
    draw.text((120, y), "Tên đơn vị: Công ty TNHH Phát triển Phần mềm Hải Âu", fill=(20, 20, 20), font=font_bold)
    y += 28
    draw.text((120, y), "Địa chỉ: Tầng 8, Tháp Phần mềm Sáng Tạo, Quận Cầu Giấy, TP. Hà Nội", fill=(40, 40, 40), font=font_body)
    y += 28
    draw.text((120, y), "Mã số thuế: 0109876543 - Điện thoại: (024) 3799 1111", fill=(40, 40, 40), font=font_body)
    y += 50

    # Clause 1
    draw.text((100, y), "ĐIỀU 1: PHẠM VI DỊCH VỤ VÀ NỘI DUNG THỰC HIỆN", fill=(10, 30, 80), font=font_bold)
    y += 30
    draw.text((120, y), "1.1 Bên B nhận cung cấp bản quyền phần mềm phân tích hóa đơn điện tử tự động.", fill=(40, 40, 40), font=font_body)
    y += 28
    draw.text((120, y), "1.2 Tích hợp hệ thống trích xuất dữ liệu OCR và đối soát sổ sách kế toán cho Bên A.", fill=(40, 40, 40), font=font_body)
    y += 28
    draw.text((120, y), "1.3 Toàn bộ mã nguồn và tài liệu chuyển giao tuân thủ quy chuẩn kỹ thuật an toàn.", fill=(40, 40, 40), font=font_body)

    # Footer
    draw.line([(80, PAGE_HEIGHT - 100), (PAGE_WIDTH - 80, PAGE_HEIGHT - 100)], fill=(200, 200, 200), width=1)
    draw.text((PAGE_WIDTH // 2 - 40, PAGE_HEIGHT - 80), "Trang 1 / 2", fill=(120, 120, 120), font=font_body)

    fields = [
        {
            "id": "p5_contract_no",
            "page": 5,
            "document": "page_05_multipage_p1.png",
            "name": "Số hiệu hợp đồng kinh tế",
            "type": "code",
            "value": "HĐ-2026/SK-HA/01",
        },
        {
            "id": "p5_contract_date",
            "page": 5,
            "document": "page_05_multipage_p1.png",
            "name": "Ngày ký kết hợp đồng",
            "type": "date",
            "value": "2026-04-18",
        },
        {
            "id": "p5_client_name",
            "page": 5,
            "document": "page_05_multipage_p1.png",
            "name": "Tên pháp nhân Bên A",
            "type": "text",
            "value": "Công ty Cổ phần Công nghệ Sao Kim",
        },
        {
            "id": "p5_vendor_name",
            "page": 5,
            "document": "page_05_multipage_p1.png",
            "name": "Tên pháp nhân Bên B",
            "type": "text",
            "value": "Công ty TNHH Phát triển Phần mềm Hải Âu",
        },
    ]
    return im, fields


# ==============================================================================
# Page 6: Multi-page Contract (Page 2/2) - Amounts & Signatures
# ==============================================================================
def render_page_6(font_path: str) -> tuple[Image.Image, list[dict[str, Any]]]:
    """Page 6: Page 2 of multi-page Vietnamese contract with financial amounts and dates."""
    im = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), color=(255, 255, 255))
    draw = ImageDraw.Draw(im)

    font_title, _ = resolve_font(20)
    font_bold, _ = resolve_font(16)
    font_body, _ = resolve_font(15)
    font_mono, _ = resolve_font(15, prefer_mono=True)

    y = 60
    draw.text((100, y), "HỢP ĐỒNG DỊCH VỤ CÔNG NGHỆ THÔNG TIN (TIẾP THEO)", fill=(10, 30, 80), font=font_title)
    draw.text((PAGE_WIDTH - 360, y + 5), "Số: HĐ-2026/SK-HA/01", fill=(60, 60, 60), font=font_mono)
    y += 35
    draw.line([(80, y), (PAGE_WIDTH - 80, y)], fill=(200, 200, 200), width=1)
    y += 40

    # Clause 2
    draw.text((100, y), "ĐIỀU 2: GIÁ TRỊ VÀ PHƯƠNG THỨC THANH TOÁN", fill=(10, 30, 80), font=font_bold)
    y += 35

    draw.rectangle([100, y, PAGE_WIDTH - 100, y + 170], fill=(248, 250, 255), outline=(190, 205, 230))
    draw.text((120, y + 15), "1. Giá trị dịch vụ trước thuế:", fill=(30, 30, 30), font=font_body)
    draw.text((PAGE_WIDTH - 380, y + 15), "450.000.000 VNĐ", fill=(10, 10, 10), font=font_mono)

    draw.text((120, y + 50), "2. Thuế suất Giá trị gia tăng (GTGT 10%):", fill=(30, 30, 30), font=font_body)
    draw.text((PAGE_WIDTH - 380, y + 50), "45.000.000 VNĐ", fill=(10, 10, 10), font=font_mono)

    draw.line([(120, y + 90), (PAGE_WIDTH - 120, y + 90)], fill=(190, 205, 230), width=1)

    draw.text((120, y + 105), "3. Tổng giá trị thanh toán sau thuế:", fill=(10, 30, 80), font=font_bold)
    draw.text((PAGE_WIDTH - 380, y + 105), "495.000.000 VNĐ", fill=(180, 20, 20), font=font_mono)

    draw.text((120, y + 138), "(Bằng chữ: Bốn trăm chín mươi lăm triệu đồng chẵn)", fill=(70, 70, 70), font=font_body)
    y += 205

    # Clause 3
    draw.text((100, y), "ĐIỀU 3: HIỆU LỰC THI HÀNH VÀ CAM KẾT CHUNG", fill=(10, 30, 80), font=font_bold)
    y += 35
    draw.text((120, y), "3.1 Hợp đồng có hiệu lực thi hành kể từ ngày: 01/05/2026 đến hết ngày 31/12/2026.", fill=(30, 30, 30), font=font_body)
    y += 28
    draw.text((120, y), "3.2 Hai bên cam kết thực hiện đúng và đầy đủ các điều khoản đã thỏa thuận.", fill=(30, 30, 30), font=font_body)
    y += 28
    draw.text((120, y), "3.3 Mọi tranh chấp phát sinh sẽ được ưu tiên giải quyết qua thương lượng hòa giải.", fill=(30, 30, 30), font=font_body)
    y += 65

    # Signatures
    draw.text((160, y), "ĐẠI DIỆN HỢP PHÁP BÊN A", fill=(10, 10, 10), font=font_bold)
    draw.text((PAGE_WIDTH - 420, y), "ĐẠI DIỆN HỢP PHÁP BÊN B", fill=(10, 10, 10), font=font_bold)
    y += 25
    draw.text((160, y), "(Ký, ghi rõ họ tên và đóng dấu)", fill=(100, 100, 100), font=font_body)
    draw.text((PAGE_WIDTH - 420, y), "(Ký, ghi rõ họ tên và đóng dấu)", fill=(100, 100, 100), font=font_body)
    y += 100
    draw.text((160, y), "[ĐÃ KÝ ĐIỆN TỬ]", fill=(120, 120, 120), font=font_mono)
    draw.text((PAGE_WIDTH - 420, y), "[ĐÃ KÝ ĐIỆN TỬ]", fill=(120, 120, 120), font=font_mono)

    # Footer
    draw.line([(80, PAGE_HEIGHT - 100), (PAGE_WIDTH - 80, PAGE_HEIGHT - 100)], fill=(200, 200, 200), width=1)
    draw.text((PAGE_WIDTH // 2 - 40, PAGE_HEIGHT - 80), "Trang 2 / 2", fill=(120, 120, 120), font=font_body)

    fields = [
        {
            "id": "p6_subtotal_amount",
            "page": 6,
            "document": "page_06_multipage_p2.png",
            "name": "Giá trị hợp đồng trước thuế",
            "type": "amount",
            "value": "450.000.000",
            "numeric_value": 450000000,
        },
        {
            "id": "p6_vat_amount",
            "page": 6,
            "document": "page_06_multipage_p2.png",
            "name": "Tiền thuế GTGT 10%",
            "type": "amount",
            "value": "45.000.000",
            "numeric_value": 45000000,
        },
        {
            "id": "p6_total_amount",
            "page": 6,
            "document": "page_06_multipage_p2.png",
            "name": "Tổng giá trị thanh toán hợp đồng sau thuế",
            "type": "amount",
            "value": "495.000.000",
            "numeric_value": 495000000,
        },
        {
            "id": "p6_effective_date",
            "page": 6,
            "document": "page_06_multipage_p2.png",
            "name": "Ngày hiệu lực hợp đồng",
            "type": "date",
            "value": "2026-05-01",
        },
        {
            "id": "p6_clause_title",
            "page": 6,
            "document": "page_06_multipage_p2.png",
            "name": "Tiêu đề điều khoản thanh toán",
            "type": "text",
            "value": "Giá trị và phương thức thanh toán",
        },
    ]
    return im, fields


# ==============================================================================
# Orchestrator & Exporter
# ==============================================================================
def generate_benchmark(
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Generate all 6 PNG benchmark pages, 1 multi-page PDF, ground_truth.json, and manifest.json.

    Returns the manifest dictionary.
    """
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    # Set deterministic random seed
    random.seed(seed)

    # Resolve font once to track provenance
    _, resolved_font_path = resolve_font(16)

    # Generate the 6 pages
    p1_im, p1_fields = render_page_1(resolved_font_path)
    p2_im, p2_fields = render_page_2(resolved_font_path)
    p3_im, p3_fields = render_page_3(resolved_font_path)
    p4_im, p4_fields = render_page_4(resolved_font_path, seed=seed)
    p5_im, p5_fields = render_page_5(resolved_font_path)
    p6_im, p6_fields = render_page_6(resolved_font_path)

    pages = [
        ("page_01_narrow_table.png", p1_im, p1_fields),
        ("page_02_negative_numbers.png", p2_im, p2_fields),
        ("page_03_confusing_chars.png", p3_im, p3_fields),
        ("page_04_degraded_scan.png", p4_im, p4_fields),
        ("page_05_multipage_p1.png", p5_im, p5_fields),
        ("page_06_multipage_p2.png", p6_im, p6_fields),
    ]

    all_fields: list[dict[str, Any]] = []
    generated_file_entries: list[dict[str, Any]] = []

    # 1. Save all PNG files
    for filename, im, fields in pages:
        file_path = out_path / filename
        im.save(file_path, format="PNG")
        sha = compute_sha256(file_path)
        f_size = file_path.stat().st_size
        generated_file_entries.append({
            "path": filename,
            "rel_path": f"bench/vision/synthetic/{filename}",
            "format": "PNG",
            "page_count": 1,
            "bytes": f_size,
            "sha256": sha,
        })
        all_fields.extend(fields)

    # 2. Save 2-page PDF from Page 5 and Page 6
    pdf_filename = "multipage_contract.pdf"
    pdf_path = out_path / pdf_filename
    p5_im.save(
        pdf_path,
        format="PDF",
        save_all=True,
        append_images=[p6_im],
        resolution=150.0,
        creationDate=FIXED_PDF_TIME,
        modDate=FIXED_PDF_TIME,
    )
    pdf_sha = compute_sha256(pdf_path)
    pdf_size = pdf_path.stat().st_size
    generated_file_entries.append({
        "path": pdf_filename,
        "rel_path": f"bench/vision/synthetic/{pdf_filename}",
        "format": "PDF",
        "page_count": 2,
        "bytes": pdf_size,
        "sha256": pdf_sha,
        "source_pages": ["page_05_multipage_p1.png", "page_06_multipage_p2.png"],
    })

    # 3. Write ground_truth.json (schema_version = 1)
    gt_data = {
        "schema_version": 1,
        "description": "Ground truth annotations for synthetic vision benchmark documents",
        "seed": seed,
        "generator": "bench/vision/generate.py",
        "total_fields": len(all_fields),
        "fields": all_fields,
    }
    gt_path = out_path / "ground_truth.json"
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump(gt_data, f, ensure_ascii=False, indent=2)

    # 4. Write manifest.json (schema_version = 1)
    checksums = {entry["path"]: entry["sha256"] for entry in generated_file_entries}
    checksums.update({entry["rel_path"]: entry["sha256"] for entry in generated_file_entries})

    manifest_data = {
        "schema_version": 1,
        "generator": "bench/vision/generate.py",
        "seed": seed,
        "deterministic_bytes": True,
        "pdf_fixed_epoch": 1700000000,
        "resolved_font": resolved_font_path,
        "files": generated_file_entries,
        "checksums": checksums,
    }
    manifest_path = out_path / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)

    return manifest_data


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic vision benchmark documents.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Target output directory (default: bench/vision/synthetic)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Random seed for deterministic generation (default: 42)",
    )
    args = parser.parse_args()

    manifest = generate_benchmark(output_dir=args.output_dir, seed=args.seed)
    print(f"Generated {len(manifest['files'])} synthetic benchmark files in {args.output_dir}:")
    for f in manifest["files"]:
        print(f"  - {f['path']} ({f['format']}, {f['bytes']} bytes, sha256={f['sha256'][:16]}...)")
    print(f"Manifest written to: {args.output_dir / 'manifest.json'}")
    print(f"Ground truth written to: {args.output_dir / 'ground_truth.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
