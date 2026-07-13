# PolyKit

Claude Code plugin gom multi-vendor CLI tooling: **doctor** (trạng thái vendor), **dispatch** (giao task cho vendor), **failover** (cảnh báo quota), **watcher** (theo dõi model/version). Python-first, chạy macOS / Windows / Linux. Vendor thiếu = degrade, không crash.

## Prereqs
- **git**, **Python 3.9+**, **Claude Code**.
- Vendor CLIs = tùy chọn (cài cái nào dùng cái đó). PolyKit tự detect + báo cái nào chưa auth.
- Không cần `pip install` gì — chỉ stdlib. (`platformdirs` tùy chọn để path chuẩn hơn.)

## Cài (Mac & Windows như nhau)
```
claude plugin marketplace add github.com/nightskat/polykit
claude plugin install polykit@polykit
```
Xong. Mở session mới, gõ `/polykit:doctor` xem trạng thái.

## Lệnh
| Lệnh | Làm gì |
|---|---|
| `/polykit:doctor` | Bảng trạng thái mọi vendor (`ready` / `installed_not_authed` / `not_installed` / `quota_capped`) + hint auth |
| `/polykit:dispatch <vendor> [model] -- <prompt>` | Giao task; vendor thiếu → degraded result, không lỗi |
| `/polykit:failover --pressure N` | Quota còn thấp → gợi ý handoff (mặc định `--dry-run`, thêm `--send` để ping Telegram thật) |
| `/polykit:watcher` | Diff model/version vendor so tuần trước, báo khi đổi |

Chạy trực tiếp không qua Claude cũng được: `python3 bin/doctor.py`, `echo "prompt" | python3 bin/dispatch.py codex --result-json`, v.v.

## Vendor — cài & auth
Chạy `/polykit:doctor` bất cứ lúc nào để xem cái nào chưa sẵn sàng + lệnh auth cụ thể.

| Vendor | Cách sẵn sàng |
|---|---|
| **Claude** | Đã auth sẵn qua Claude Code (host) |
| **Codex** | Cài Codex CLI → `codex login` |
| **Gemini** | Cài Gemini CLI → chạy `gemini` rồi `/auth`. (Hoặc chỉ cần `GEMINI_API_KEY` cho lane API) |
| **Grok** | Cài Grok CLI → `grok` để auth |
| **OpenRouter** | Lấy key **free** tại [openrouter.ai/keys](https://openrouter.ai/keys) → `export OPENROUTER_API_KEY=...` (Windows: `setx OPENROUTER_API_KEY ...`). Model free mặc định: `google/gemini-2.0-flash-exp:free` |

## Mac vs Windows
- **doctor / dispatch / failover**: chạy y hệt cả hai (Python stdlib).
- **watcher tự chạy hàng tuần**: Mac dùng `launchd`, Windows dùng `schtasks` — tự chọn theo OS. Linux: chạy watcher thủ công (cron adapter chưa làm).
- Ping Telegram (failover `--send`): mặc định trỏ script của tác giả. Máy khác đặt `POLYKIT_NOTIFIER` trỏ script gửi tin của bạn, hoặc bỏ qua (chỉ hiện message).

## Nguyên tắc
- Vendor thiếu/chưa auth/hết quota → **degrade rõ ràng**, không bao giờ crash.
- Claude lane bị **giới hạn** (plan-mode, không tool) theo ToS — không dùng làm worker.
- State (cache) tự sinh; xoá được, tự tạo lại.

MIT. Repo: github.com/nightskat/polykit
