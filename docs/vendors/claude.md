# Claude — host & orchestrator

> Cập nhật 2026-08-03. Version live: `/polykit:doctor` (đọc live, đừng tin số trong docs).
> Snapshot lúc viết: **Claude Code 2.1.220**.

## Model đang có (snapshot 2026-08-03)
Claude Code quản model, **không qua PolyKit** — đổi bằng `/model` trong session hoặc `--model`.

| Model | ID | Dùng khi |
|---|---|---|
| Opus 5 | `claude-opus-5` | Orchestrate, review, việc khó |
| Sonnet 5 | `claude-sonnet-5` | Hub mặc định, việc thường |
| Haiku 4.5 | `claude-haiku-4-5-20251001` | Q&A ngắn, việc cơ khí |
| Fable 5 | `claude-fable-5` | — |

Lane dispatch (`/polykit:dispatch claude`) luôn ép `--effort low --permission-mode plan
--tools ""` bất kể model — không dùng làm worker.

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
