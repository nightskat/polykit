# Synthetic Vision Benchmark: Vietnamese Financial & Banking Documents

Hệ thống đánh giá độ chính xác trích xuất quang học (Vision LLM vs Local OCR) trên các dạng tài liệu khó thường gặp trong báo cáo tài chính (BCTC) và hồ sơ ngân hàng Việt Nam.

Mục tiêu chính: Trả lời câu hỏi **"Vision LLM có bù được OCR truyền thống (vnocr) ở các trang khó không?"** bằng số liệu định lượng chính xác theo kiểu dữ liệu, không dùng difflib và không dựa vào điểm tự tin (confidence) của mô hình.

---

## 1. Dữ liệu thử nghiệm tổng hợp (Synthetic Dataset)

Toàn bộ dữ liệu nằm tại `bench/vision/synthetic/`, được sinh bằng `bench/vision/generate.py` với seed cố định (`seed=42`). 100% dữ liệu là giả lập, không chứa thông tin cá nhân (zero real PII).

Gồm 6 trang PNG và 1 file PDF 2 trang:
1. `page_01_narrow_table.png`: Bảng tài chính nhiều cột hẹp, các số tiền lớn có phân cách chấm hàng nghìn dạng `1.234.567.890`.
2. `page_02_negative_numbers.png`: Số âm kế toán đặt trong ngoặc đơn dạng `(12.345)`, `(98.765.432)`.
3. `page_03_confusing_chars.png`: Ký tự dễ nhầm lẫn quang học `0/O`, `1/l`, `5/6/8` và năm tài chính `2026` vs `2006` (`HD-2026-O0l1586B`, `REF-2006-0Ol1`, `SERIES-8568-2006`).
4. `page_04_degraded_scan.png`: Mô phỏng scan thực tế suy giảm chất lượng (xoay nghiêng skew, làm mờ blur, nhiễu hạt noise, nén JPEG artifact).
5. `page_05_multipage_p1.png`: Hợp đồng tiếng Việt có dấu đầy đủ (Trang 1/2).
6. `page_06_multipage_p2.png`: Hợp đồng tiếng Việt, bảng thanh toán, chữ ký điện tử (Trang 2/2).
7. `multipage_contract.pdf`: File PDF 2 trang ghép từ trang 5 và trang 6.

Ground truth được lưu tại `bench/vision/synthetic/ground_truth.json` (`schema_version: 1`), gồm 28 trường (đang tiếp tục được mở rộng từng ô) với các thuộc tính: `id`, `type`, `value`, `document`, và `row`/`column` tùy chọn.

---

## 2. Công cụ chấm điểm (`bench/vision/score.py`)

### 2.1. Đánh giá theo kiểu dữ liệu xác định (Deterministic Typed Evaluation)

Scorer không dùng so sánh xấp xỉ `difflib`, không tin confidence:
- **`amount` (Số tiền)**: So sánh giá trị số học tuyệt đối qua `Decimal`.
  - Hỗ trợ định dạng hàng nghìn dấu chấm chuẩn Việt Nam: `1.234.567.890` -> `Decimal('1234567890')`.
  - Hỗ trợ số âm trong ngoặc đơn kế toán: `(12.345)` -> `Decimal('-12345')` và dấu âm `-12.345` -> `Decimal('-12345')`.
  - **Quy tắc nghiêm ngặt**: Cấm tuyệt đối việc lọc bỏ chữ tùy tiện (không permissive stripping letters); từ chối kiểu boolean (`True`/`False`); từ chối `NaN`/`Infinity`.
- **`date` (Ngày tháng)**: So sánh đối tượng ngày lịch hợp lệ (`datetime.date`).
  - Hỗ trợ chuẩn ISO (`YYYY-MM-DD`) và chuẩn Việt Nam (`DD/MM/YYYY`, `DD-MM-YYYY`).
  - Kiểm tra tính hợp lệ lịch (từ chối ngày không tồn tại như `31/02/2026`).
  - Phát hiện chính xác nhầm lẫn năm: `2006-01-15` khác `2026-01-15`.
- **`code` (Mã số)**: So sánh chuỗi CHÍNH XÁC (EXACT string match).
  - Phân biệt hoa thường, phân biệt từng ký tự nhạy cảm: `0` (số không) khác `O` (chữ O hoa), `1` (số một) khác `l` (chữ l thường).
- **`text` (Văn bản)**: Chuẩn hóa Unicode NFC và chuẩn hóa khoảng trắng DUY NHẤT.
  - Giữ nguyên tính phân biệt chữ hoa / chữ thường (case-sensitive).

### 2.2. Quy tắc ánh xạ trường
- Mô hình trả về JSON object ánh xạ `field_id -> giá trị`.
- Thiếu trường (`missing`), giá trị null, hoặc lỗi kiểu dữ liệu đều được tính là **SAI** (không bị loại trừ khỏi tổng số trường).
- Trình phân tích JSON hỗ trợ:
  1. Plain JSON string.
  2. Markdown fenced block (` ```json ... ``` `).
  3. JSON nằm giữa văn bản đàm thoại (tìm `{ ... }` ngoài cùng).
  4. Stream JSONL event text từ `opencode --format json` (định dạng `DispatchResult.stdout`).
- Tuyệt đối không dùng ground truth để điền hoặc đoán trước đáp án.

### 2.3. Lệnh chấm điểm mô hình (Model Prediction Scoring)

```bash
python3 bench/vision/score.py \
  --ground-truth bench/vision/synthetic/ground_truth.json \
  --prediction path/to/prediction.json \
  --output path/to/score_report.json \
  --summary
```

Hoặc đọc trực tiếp từ pipe / stdin:

```bash
cat path/to/prediction.json | python3 bench/vision/score.py \
  --ground-truth bench/vision/synthetic/ground_truth.json \
  --prediction - \
  --summary
```

---

## 3. Baseline `vnocr`: Thước đo thu hồi token trung thực (`--ocr-text`)

### 3.1. Phân định rõ ràng: Token Recovery ≠ Cell Accuracy
`vnocr` (công cụ OCR chạy Apple Vision on-device) xuất ra dòng văn bản thuần túy theo từng trang (`===== page_...png ...`), không có thông tin tọa độ ô hay quan hệ cấu trúc cột/dòng.

Việc gán bừa kết quả OCR vào từng `field_id` của bảng là **không trung thực**. Do đó, hệ thống cài đặt cờ `--ocr-text` để đo **chỉ số thu hồi token/dòng ứng viên (Upper-bound Token Recovery)**:
- Đo lường: Trong văn bản thô của từng trang, có xuất hiện token hoặc dòng nào khớp chính xác với giá trị ground truth hay không?
- **Nhãn độc lập**: Báo cáo lưu thành tệp riêng và được dán nhãn rõ ràng: `upper_bound_token_recovery`, tuyệt đối không đánh đồng với độ chính xác ô bảng (`cell_accuracy`), vì các token trùng lặp không chứng minh được vị trí dòng/cột.
- **Không fuzzy**: Nhầm 1 chữ số trong số tiền hoặc sai ký tự trong mã số (ví dụ OCR đọc `HC-2028-0011586B` thay vì `HD-2026-O0l1586B`) đều tính là không thu hồi được (`recovered=False`).

### 3.2. Lệnh chấm Baseline `vnocr`

Chấm trên bản trích xuất OCR có sẵn tại repo:

```bash
python3 bench/vision/score.py \
  --ground-truth bench/vision/synthetic/ground_truth.json \
  --ocr-text docs/plans/vnocr-v3/ocr.raw.txt \
  --output docs/plans/vnocr-v3/recovery_report.json \
  --summary
```

**Kết quả đo thực tế của `vnocr` trên bộ dữ liệu tổng hợp hiện tại:**

```text
=== Vision Benchmark Evaluation [upper_bound_token_recovery] ===
NOTE: Upper-bound token recovery, NOT cell accuracy. Raw OCR does not associate extracted tokens to field IDs or table cells. Duplicate tokens cannot prove row/column association.

Overall Recovery: 11/28 (39.29%)

--- By Document ---
  page_01_narrow_table.png           :  1/ 5 ( 20.00%)
  page_02_negative_numbers.png       :  3/ 5 ( 60.00%)
  page_03_confusing_chars.png        :  1/ 5 ( 20.00%)
  page_04_degraded_scan.png          :  3/ 4 ( 75.00%)
  page_05_multipage_p1.png           :  0/ 4 (  0.00%)
  page_06_multipage_p2.png           :  3/ 5 ( 60.00%)

--- By Type ---
  amount         :  6/11 ( 54.55%)
  date           :  3/ 6 ( 50.00%)
  code           :  2/ 7 ( 28.57%)
  text           :  0/ 4 (  0.00%)
```

---

## 4. Runner CLI (`bench/vision/run.py`)

Runner thực hiện điều phối kiểm chuẩn qua `bin/dispatch.py`, hỗ trợ DeepSeek (`deepseek-v4.1-flash`, effort `high`) và GLM (`glm-5.3-flash`, effort `max`).

### 4.1. Nguyên tắc thiết kế & Ranh giới an toàn
1. **Lọc sạch Prompt (Zero Answer Leaks)**: Prompt sinh ra chỉ chứa `id`, `type`, `name`, `row`, `column`. Tuyệt đối không chứa `value` hay `numeric_value`. Tên trường bị rò rỉ đáp án (như `chứa O0l1586B`, `chứa 8568`) đều được tự động tẩy sạch.
2. **Cảnh báo Unsandboxed Harness**: Ghi log rõ ràng: Cơ chế cấm bằng prompt ("không đọc file workspace") **không phải bằng chứng bảo mật mạnh**. Kết quả benchmark cần được hiểu trong giới hạn kiến trúc này.
3. **An toàn Shell & Bảo vệ ghi đè**: Các tham số gọi lệnh truyền dưới dạng danh sách `argv` an toàn (không dùng shell string, an toàn tuyệt đối với đường dẫn có dấu cách). Tệp kết quả được bảo vệ chống ghi đè trừ khi có cờ `--overwrite`.
4. **Lưu vết tức thì & Đo đạc**: Mọi lệnh gọi đều lưu ngay lập tức raw `stdout`, `stderr`, mã thoát `returncode` và thời gian thực thi (latency). Thống kê `quota_attempts` (số lượt gọi dispatch) và `inference_success` (số lượt suy luận thành công), không gọi là đơn vị quota nhà cung cấp vì không đo được usage nội bộ.

### 4.2. Lệnh chạy thực tế (Live Execution Commands)

> **Lưu ý**: Trước khi chạy lệnh live, đảm bảo môi trường đã cấu hình quyền dispatch opencode với các cờ hợp lệ: `--data-class code-nopii --synthetic-vision`.

#### A. Chạy DeepSeek-v4.1-Flash trên 6 trang ảnh PNG:
```bash
python3 bench/vision/run.py \
  --model deepseek-v4.1-flash \
  --effort high \
  --mode images \
  --output-dir bench/vision/results/deepseek_v4_1_flash_images \
  --timeout 600
```

#### B. Chạy GLM-5.3-Flash trên 6 trang ảnh PNG:
```bash
python3 bench/vision/run.py \
  --model glm-5.3-flash \
  --effort max \
  --mode images \
  --output-dir bench/vision/results/glm_5_3_flash_images \
  --timeout 600
```

#### C. Chạy GLM-5.3-Flash nhận PDF trực tiếp (2 trang):
```bash
python3 bench/vision/run.py \
  --model glm-5.3-flash \
  --effort max \
  --mode pdf \
  --output-dir bench/vision/results/glm_5_3_flash_pdf \
  --timeout 600
```

#### D. Chạy DeepSeek-v4.1-Flash trên PDF (qua chuyển đổi pdftoppm tự động của gate):
```bash
python3 bench/vision/run.py \
  --model deepseek-v4.1-flash \
  --effort high \
  --mode pdf \
  --output-dir bench/vision/results/deepseek_v4_1_flash_pdf \
  --timeout 600
```

#### E. Chạy kiểm tra mô phỏng (Dry-run mode - không tốn quota, không gọi mạng):
```bash
python3 bench/vision/run.py \
  --dry-run \
  --mode all \
  --output-dir /tmp/vision_bench_dry_run \
  --overwrite
```

---

## 5. Kiểm thử tự động (Automated Verification)

Chạy toàn bộ 16 bài kiểm thử xác minh cho scorer, runner, bộ lọc leak, và cơ chế token recovery của baseline:

```bash
~/.pyenv/versions/3.11.8/bin/python -m pytest tests/test_vision_bench_score.py -v
```

Chạy kiểm thử bộ sinh dữ liệu tổng hợp:

```bash
~/.pyenv/versions/3.11.8/bin/python -m pytest tests/test_vision_bench_generator.py -v
```

Chạy toàn bộ test suite của repository:

```bash
~/.pyenv/versions/3.11.8/bin/python -m pytest tests/ -q
```
