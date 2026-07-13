# PolyKit — Nghiệm thu & Bàn giao

**Phiên bản:** v0.2.1 · **Ngày:** 2026-07-13 · **Repo:** https://github.com/nightskat/polykit (public, MIT)

## Phạm vi
Plugin Claude Code gom multi-vendor CLI tooling: **doctor** (trạng thái vendor), **dispatch**
(giao task), **failover** (cảnh báo quota), **watcher** (theo dõi model/version). Python-first,
chạy macOS/Windows/Linux. Nguyên tắc: vendor thiếu = degrade, không crash.

## Nghiệm thu theo năng lực

| Năng lực | Acceptance | Bằng chứng |
|---|---|---|
| doctor | Detect 5 vendor, state machine 4 trạng thái, state.json schema_version=1 | Chạy thật: Claude/Codex/Gemini/Grok `ready`, OpenRouter theo key |
| dispatch | Vendor chạy thật; thiếu vendor → degraded (skipped), không lỗi | codex/gemini/**openrouter** trả kết quả thật; no-key → skipped |
| failover | pressure→ping trước, cap→ping reactive, lỗi lạ→im | 4 nhánh verify tay; `--dry-run` không gửi thật |
| watcher | Đổi model/version → 1 alert; offline→skip; notify fail→retry | Verify tay: bump→1 alert, offline noop, retry |
| ToS | Claude lane bounded, không spawn full-worker | Negative test khóa mọi cờ bounded |
| Cross-platform | Chạy Python 3.9+; Mac launchd / Win schtasks | 4 entrypoint chạy trên 3.9.6 lẫn 3.14 |

## Đã test LIVE (không chỉ unit test)
- **79 unit test** pass (Python 3.11).
- **Cài thật từ GitHub**: `claude plugin marketplace add ...` + `install` → 0.2.1, 4 lệnh nhận đủ.
- **Slash command thật**: `claude -p "/polykit:doctor"` → parse .md → chạy bin → bảng vendor.
- **Dispatch API thật**: codex→`pong`, gemini→`pong`, **OpenRouter→`pong`** (model free).
- **Degraded path thật**: OR no-key → skipped/installed_not_authed; 429→quota_capped.

## Giới hạn đã biết (backlog)
- Free model OpenRouter **xoay vòng** — model mặc định có thể 404 khi bị gỡ. Cách xử: truyền model
  tường minh, hoặc cập nhật default. TODO: auto-pick model `:free` còn sống.
- Windows scheduler (schtasks) build theo thiết kế, **chưa test trên máy Win thật** (không có máy).
- Linux watcher auto-schedule (cron adapter) PARKED — chạy watcher thủ công.
- OR lane fake-opener test đầy đủ; các vendor CLI khác test qua fixture/mock.
- PARKED (mở khi pain lặp ≥3): quota ledger, benchmark tiers, canary, MCP server, SQLite.
- Ý tưởng nâng cấp: đọc structured quota từ CAUT/OpenUsage thay stderr-parsing (xem BACKLOG.md).

## Bàn giao
Cài (Mac & Win như nhau):
```
claude plugin marketplace add https://github.com/nightskat/polykit.git
claude plugin install polykit@polykit
```
Auth per-vendor + cách dùng: xem [README.md](../README.md). Chạy `/polykit:doctor` để xem cần auth gì.

## Cách build (truy vết)
Pipeline mỗi milestone: **Gemini (agy) build → Codex gpt-5.5 adversarial review → Claude tích hợp + verify + pytest**.
6 milestone spec (M1a→M4) + MVP portability fix + OR lane + schtasks. Codex bắt lỗi thật qua từng đợt
(ToS test yếu, depth bypass, 402/429 false-positive, offline≠not_installed, notify mất cảnh báo,
paths lệch platformdirs, key whitespace, default model 404). Tất cả vá + verify.
