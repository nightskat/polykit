# Chia việc đa vendor — playbook

> Cập nhật 2026-07-30. Đúc từ thực chiến (case BCTC 30/07: 3 vendor cùng đọc 1 file, 3 kết quả
> khác nhau ở đúng những chỗ cần biết ý người). Guide từng vendor: `vendors/*.md`.

## Nguyên tắc lõi

1. **Model không thiếu năng lực — thiếu người hướng dẫn ở chỗ rẽ.** Trước khi chia việc,
   liệt kê các "chỗ rẽ" (điểm task có ≥2 cách làm hợp lý, chọn sai là hỏng). Chỗ rẽ chưa có
   đáp án của người → KHÔNG dispatch phần đó, chỉ dispatch phần đã rõ.
2. **Maker–checker khác vendor.** Vendor nào làm thì vendor khác (hoặc Claude host) review.
   Không nghiệm thu output vendor bằng chính vendor đó.
3. **Kết quả số liệu phải qua validator máy** (script kiểm tra tất định), không nghiệm thu
   bằng mắt hay bằng lời model tự khai.

## Gate — học từ 2 vụ fail thật (2026-07-30)

| Vụ | Vendor | Hành vi | Gate chặn |
|---|---|---|---|
| Bịa số ép cân đối | Gemini/Agy | Hardcode tiền 11 tỷ cho bảng "đẹp", cache tự mâu thuẫn | Validator máy: cân đối + đối chiếu nguồn từng số |
| Sửa theo giả định | Codex | Tự liệt kê 9 câu hỏi chưa trả lời, vẫn xuất file đã sửa | **Câu hỏi mở > 0 → chỉ nhận báo cáo, không nhận file/code đã sửa** |

Hai gate này áp cho MỌI vendor, mọi task số liệu — không phải phạt riêng ai.

## PII — luật cứng

- PII thật (tên KH, CIF, MST, số HĐ, số dư, sao kê): **chỉ Claude host** được xử lý.
- Muốn dispatch việc có PII → **khử định danh trước** (thay tên/CIF bằng mã, làm tròn hoặc
  xáo số nếu bản chất việc cho phép), hoặc tách phần không-PII ra mà giao.
- OpenRouter nghiêm nhất: không bao giờ, kể cả "chỉ một cái tên".
- Áp cho cả file đính kèm, screenshot, và dữ liệu nhét trong prompt.

## Bảng chia việc theo loại task

| Loại task | Maker | Checker | Ghi chú |
|---|---|---|---|
| Code mới / refactor | Claude host | Codex | Codex review adversarial |
| Review code | Codex | — | Lane số 1 |
| Audit số liệu / văn bản | Codex | Claude + validator | Nhớ gate câu-hỏi |
| Prose/classify/OCR bulk | Gemini (agy nếu có) | Claude spot-check | Value lane |
| OCR batch >50 / classify volume | OpenRouter free | Validator + spot-check | 1K RPD |
| Second opinion / debate | Grok | — | Không dùng một mình |
| Việc có PII thật | Claude host | Claude host | Không dispatch |
| Orchestrate / tổng hợp | Claude host | người | — |

## Quy trình dispatch 1 task (chuẩn)

1. Viết task: `objective, expected_output, timeout` (contract P4) + **liệt kê chỗ rẽ đã có đáp án**.
2. Kiểm PII → khử định danh nếu cần.
3. `/polykit:dispatch <vendor> -- <task>` (model để auto trừ khi có lý do ghim).
4. Nhận result JSON → chạy validator (nếu là số liệu/code) → checker khác vendor review.
5. Kết quả + bài học (nếu có) ghi về artifact của dự án — không để trong chat.

## Tham khảo máy-riêng (tùy chọn, không bắt buộc để dùng PolyKit)
- Bench nội bộ & traits: `~/Claude/CHEATSHEETS/vendor-intelligence/` + plugin model-intelligence.
- Routing digest: `~/.claude/rules/routing-summary.md`.
