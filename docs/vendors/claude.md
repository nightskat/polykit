# Claude — host & orchestrator

> Cập nhật 2026-07-30. Model/version hiện tại: chạy `/polykit:doctor` (đọc live, đừng tin số trong docs).

## Vai trò trong PolyKit
- **Host**: PolyKit là Claude Code plugin — Claude là nơi ra lệnh, tổng hợp, review.
- **KHÔNG phải worker lane.** Dispatch tới `claude` chỉ được lane **bounded** (plan-mode, no tools,
  không giữ session) theo ToS — xem SPEC P3, có negative test.

## Cài & auth
Đã auth sẵn qua Claude Code (chính là app đang chạy plugin). Không cần bước nào thêm.

## Khi nào dùng
| Việc | Ghi chú |
|---|---|
| Orchestrate: chia việc, tổng hợp kết quả vendor | Vai trò mặc định |
| Review chéo output vendor khác | Maker–checker: vendor làm, Claude check |
| **Mọi việc đụng PII thật** | Lane DUY NHẤT được phép — xem `../CHIA-VIEC.md` §PII |
| Việc cần tool (file, bash, MCP) | Chỉ host làm được; lane dispatch không có tool |

## Khi nào KHÔNG dùng
- Task bulk rẻ tiền (OCR hàng loạt, classify volume) — đốt quota host vô ích, đẩy sang Gemini/OR.
- Làm worker qua dispatch — bị chặn bởi thiết kế, đừng tìm cách lách.

## Giới hạn & sự cố
- Quota 5h cap: failover Sonnet → Haiku → OR (xem `/polykit:failover`).
- Claude lane trong dispatch trả về recommendation-only (không thực thi) — đó là hành vi đúng,
  không phải bug.
