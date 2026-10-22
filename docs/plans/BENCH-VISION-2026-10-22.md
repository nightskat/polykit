# Bench vision tổng hợp — 22/10/2026

## Kết luận
DeepSeek high đáng thử làm tầng đối chiếu SỐ: vòng sạch gợi ý đạt 59/59 ô tiền, 137/142 trường tổng (96,48%), 111,53s/6 trang. GLM max đạt 59/59 ô tiền, 136/142 (95,77%), 183,12s. Cả hai vẫn đọc sai O/0 và l/1; không dùng làm nguồn quyết định/mã hồ sơ tự động.
Trong bộ synthetic này, mỗi model đọc đúng 94 trường mà raw vnocr không phục hồi được. Đây là bằng chứng bổ sung trên 6 trang, KHÔNG phải kết luận độ chính xác trên hồ sơ thật.

## Thiết kế và hợp đồng chấm
- Generator PIL seed 42; 6 PNG, PDF ảnh 2 trang từ trang 5–6, manifest schema_version=1 + SHA256; 142 trường, bao phủ từng ô dữ liệu bảng 1–2. Không dữ liệu khách hàng/người thật.
- Gate chỉ nhận artifact trong bench/vision/synthetic dưới root của module, manifest khớp registry hash ghim trong code. File khác/manifest giả/symlink/tamper/sensitive vẫn blocked. Hermes attachments vẫn blocked; không mở lane PGBank.
- Tiền so Decimal, ngoặc đơn = âm, nhận đúng whitelist hậu tố VND/VNĐ/đ; không xoá chữ tùy tiện. Ngày so ngày hợp lệ; mã so chuỗi exact; text chỉ NFC + whitespace, giữ hoa/thường/dấu. Thiếu/không parse tính sai. Không difflib/confidence.
- Vòng chính dùng prompt CHỈ id/type/row/column cho bảng: không name nhãn hàng, không giá trị GT. Vòng cũ có gợi nhãn được giữ riêng, không dùng kết luận chính.
- Qua python bin/dispatch.py opencode, --data-class code-nopii --synthetic-vision --format json; DeepSeek --effort high, GLM --effort max, timeout 600. Mỗi ảnh một lượt; cwd scratch trống; tool-event => contaminated và loại khỏi điểm. 12 lượt PNG cuối không có tool-event.
- Harness vẫn unsandboxed: cwd trống + kiểm event không phải sandbox, không chứng minh chống đối thủ có quyền sửa repo. Model/effort là yêu cầu gửi đi; served_model chưa được CLI xác nhận.

## Model × loại lỗi (đúng/tổng; %)
| Trang / lỗi | DeepSeek high, field accuracy | GLM max, field accuracy | vnocr raw, token recovery (*) |
|---|---:|---:|---:|
| Bảng cột hẹp | 86/86; 100% | 86/86; 100% | 22/86; 25,58% |
| Âm trong ngoặc | 38/38; 100% | 37/38; 97,37% | 13/38; 34,21% |
| 0/O, 1/l, 5/6/8, năm | 3/5; 60% | 3/5; 60% | 2/5; 40% |
| Mờ/nghiêng/nhiễu/JPEG | 3/4; 75% | 3/4; 75% | 3/4; 75% |
| Tiếng Việt / PDF trang 1 dạng PNG | 3/4; 75% | 3/4; 75% | 0/4; 0% |
| Tiền + chữ / PDF trang 2 dạng PNG | 4/5; 80% | 4/5; 80% | 3/5; 60% |
| Tổng PNG | 137/142; 96,48% | 136/142; 95,77% | 43/142; 30,28% |
| Tiền, riêng theo type | 59/59; 100% | 59/59; 100% | 29/59; 49,15% |

(*) vnocr raw chỉ đo upper-bound token/line recovery trên đúng trang, KHÔNG chứng minh gán đúng hàng/cột. Không đặt bằng với field accuracy. Trường trùng token có thể được tính phục hồi nhiều lần; metric này không phải độ chính xác parser vnocr hoàn chỉnh.

## PDF, thời gian và lượt gọi
| Thử | Kết quả thật | Giây | Dispatch attempts |
|---|---|---:|---:|
| DeepSeek PNG vòng cuối | 6/6 inference; 137/142 | 111,53 | 6 |
| GLM PNG vòng cuối | 6/6 inference; 136/142 | 183,12 | 6 |
| DeepSeek PDF sau harden | pdftoppm tách 2 trang, gửi 2 ảnh; 8/9 | 19,91 | 1 |
| GLM PDF trực tiếp | HTTP400 upstream deserialize, không inference; accuracy N/A | 11,78 | 1 |
| GLM đường tách trang | hai PNG tương ứng trang 5/6 trong vòng cuối: 7/9 | nằm trong PNG ở trên | 2, đã tính |
| vnocr Apple Vision | command -v có; exit0/completed, đủ 6 trang | 1,91 | 0 cloud |
| vnocr --cross-check-mlx | engine chạy 6 trang; exit1 needs_human_reading, 5 trang bất đồng số | chưa đo wall-clock riêng | 0 cloud |

- GLM đường tách ở đây là PNG nguồn tương ứng PDF, không tuyên bố đã thử ép GLM render PDF bằng pdftoppm; direct-PDF fail được giữ nguyên, không lén fallback rồi gọi là thành công.
- Tổng dogfood vision gồm cả lỗi argv và vòng gợi nhãn: DeepSeek 21 dispatch / 14 inference; GLM 20 / 12. Không biết billing/quota units thực tế, không gọi số dispatch là token hoặc đơn vị quota. Lỗi trước inference vẫn có thể tốn request.
- Vòng đầu mỗi model 7/7 lỗi argv do thiếu -- sau -f; đã ghi BUGS và sửa. Vòng gợi nhãn tiếp theo không thay thế vòng PNG sạch cuối.

## Vision vẫn hỏng ở đâu
- Cả hai: HD-2026-O0l1586B → HD-2026-0011586B; REF-2006-0Ol1 → REF-2006-0011. Kiểu ký tự này phải giữ đối chiếu/đọc tay.
- DeepSeek vòng cuối: Phí→Phi; mã hợp đồng SK→SX. GLM: TXN→TXX, HĐ→HD, tồn đọng→tồn động.
- Cả hai trả thêm tiền tố ĐIỀU 2 ở trường chỉ yêu cầu tiêu đề; chấm text exact tính sai (boundary extraction, không phải toàn bộ chữ bị OCR sai).
- Chỉ 6 trang/1 seed, số ô bảng áp đảo tổng; synthetic layout đơn giản, không con dấu/chồng chữ/giấy thật. Chưa chứng minh độ ổn định nhiều lần, giá tiền hay hiệu quả production. Chưa có field-mapped baseline Apple Vision+MLX để so ngang hàng.

## Evidence / tái chạy
- bench/vision/{generate,run,score}.py và README.md; registry bin/lib/vision.py. Không tái sinh fixture trên font/máy khác rồi tự mở gate: hash thay phải review/cập nhật registry.
- Vòng chính: docs/plans/evidence/2026-10-22/bench-v3-{deepseek,glm}-final/run_summary.json, raw_calls/, prompts/ (lưu nguyên result JSON/status/reason/warnings/command/time).
- PDF: evidence/2026-10-22/bench-v3-deepseek-pdf-hardened/; GLM direct lỗi ở evidence/2026-10-22/bench-v3-glm-retry/raw_calls/call_07_multipage_contract_pdf.json.
- Baseline: evidence/2026-10-22/vnocr-v3-final/{run_manifest.json,ocr.raw.txt}; evidence/2026-10-22/vnocr-v3-score-numeric.json; evidence/2026-10-22/vnocr-v3-timing.json; evidence/2026-10-22/vnocr-v3-mlx/ và stderr. Hash nguồn từng trang trong manifest.
- Các vòng trước: evidence/2026-10-22/bench-v3-{deepseek,glm}/, evidence/2026-10-22/*-retry/, evidence/2026-10-22/*-rescored.json. Điểm trong *-retry ban đầu dùng parser chưa nhận hậu tố tiền; số rescored ghi rõ thay đổi chấm, không phải lượt model mới.
