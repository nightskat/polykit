# PolyKit

Claude Code plugin gom multi-vendor CLI tooling: **doctor** (trạng thái vendor), **dispatch** (giao task cho vendor), **failover** (cảnh báo quota), **watcher** (theo dõi model/version). Python-first, chạy macOS / Windows / Linux. Vendor thiếu = degrade, không crash.

## Prereqs
- **git**, **Python 3.9+**, **Claude Code**.
- Vendor CLIs = tùy chọn (cài cái nào dùng cái đó). PolyKit tự detect + báo cái nào chưa auth.
- Không cần `pip install` gì — chỉ stdlib. (`platformdirs` tùy chọn để path chuẩn hơn.)

## Cài (Mac & Windows như nhau)
```
claude plugin marketplace add https://github.com/nightskat/polykit.git
claude plugin install polykit@polykit
```
Xong. Mở session mới, gõ `/polykit:doctor` xem trạng thái.

## Lệnh
| Lệnh | Làm gì |
|---|---|
| `/polykit:doctor` | Bảng trạng thái mọi vendor (`ready` / `installed_not_authed` / `auth_unverified` / `not_installed` / `quota_capped`) + hint phù hợp |
| `/polykit:dispatch <vendor> [model] -- <prompt>` | Giao task; vendor thiếu → degraded result, không lỗi |
| `/polykit:failover --pressure N` | Quota còn thấp → gợi ý handoff (chỉ chạy thử do plugin luôn gắn `--dry-run`) |
| `/polykit:watcher` | Diff model/version vendor so tuần trước, báo khi đổi |

Chạy trực tiếp không qua Claude cũng được: `python3 bin/doctor.py`, `printf "prompt" | python3 bin/dispatch.py codex --result-json`, v.v.

Các cờ mở rộng của `bin/dispatch.py`:
- `--doctor`: Chạy lệnh `verify_cmd` cho vendor và in trạng thái.
- `--allow-unknown-model`: Cho phép gọi các model không có mặt trong danh sách JSON.
- `--no-traps`: Ẩn các cảnh báo trap trên stderr.
- `--dump-config`: In cấu hình vendor và thoát.

## Vendor — cài & auth
Chạy `/polykit:doctor` bất cứ lúc nào để xem cái nào chưa sẵn sàng + lệnh auth cụ thể. PolyKit hỗ trợ 7 vendor: `agy, dsh, grok, codex, gemini, claude, openrouter`.

| Vendor | Cách sẵn sàng |
|---|---|
| **Claude** | Đã auth sẵn qua Claude Code (host). |
| **Codex** | Cài Codex CLI → `codex login`. |
| **Gemini** | Cài Gemini CLI → chạy `gemini` rồi `/auth`. Hoặc chỉ cần biến môi trường `GEMINI_API_KEY`. |
| **Grok** | Cài Grok CLI → `grok` để auth. |
| **Agy** | Cài Antigravity CLI → chạy `agy` để auth. |
| **Dsh** | Cài Dsh CLI → export `DEEPSEEK_API_KEY=...` trong môi trường (bắt buộc, ví dụ qua `~/.zshrc`). |
| **OpenRouter** | Ghi API key vào file `~/.config/openrouter/key` hoặc export `OPENROUTER_API_KEY`. |

## Tuỳ biến JSON (config/vendors.json)
Người dùng có thể thêm vendor mới bằng cách chỉnh sửa JSON schema với các trường:
- `headless`: Lệnh chạy CLI dạng không-cần-người-dùng (ví dụ: `vendor-cli -p '<prompt>'`).
- `model_flag`: Cờ dùng để chỉ định model (ví dụ: `-m` hoặc `--model`).
- `models`: Danh sách các model hỗ trợ (list các string).
- `traps`: Danh sách các cảnh báo, lỗi tiềm ẩn khi dùng vendor (list string).
- `zero_quota_cmds`: Lệnh chạy không tốn token dùng để verify auth (`--doctor`).

## Mac vs Windows
- **doctor / dispatch / failover**: chạy y hệt cả hai (Python stdlib).
- **watcher tự chạy hàng tuần**: Mac dùng `launchd`, Windows dùng `schtasks` — tự chọn theo OS. Linux: chạy watcher thủ công (cron adapter chưa làm).

## Nguyên tắc
- Vendor thiếu/chưa auth/hết quota → **degrade rõ ràng**, không bao giờ crash.
- Claude lane bị **giới hạn** (plan-mode, không tool) theo ToS — không dùng làm worker.
- State (cache) tự sinh; xoá được, tự tạo lại.
- Các PII thật phải khử định danh trước khi dispatch.

MIT. Repo: github.com/nightskat/polykit
