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
| `/polykit:doctor` | Bảng trạng thái mọi vendor (`ready` / `installed_not_authed` / `not_installed` / `quota_capped`) + hint auth |
| `/polykit:dispatch <vendor> [model] -- <prompt>` | Giao task; vendor thiếu → degraded result, không lỗi |
| `/polykit:failover --pressure N` | Quota còn thấp → gợi ý handoff (mặc định `--dry-run`, thêm `--send` để ping Telegram thật) |
| `/polykit:watcher` | Diff model/version vendor so tuần trước, báo khi đổi |

Chạy trực tiếp không qua Claude cũng được: `python3 bin/doctor.py`, `echo "prompt" | python3 bin/dispatch.py codex --result-json`, v.v.

## Vendor — cài & auth
Chạy `/polykit:doctor` bất cứ lúc nào để xem cái nào chưa sẵn sàng + lệnh auth cụ thể.
**User guide đầy đủ từng vendor** (thế mạnh, điểm yếu đã ghi nhận, PII, sự cố): `docs/vendors/`.

| Vendor | Cách sẵn sàng | Guide |
|---|---|---|
| **Claude** | Đã auth sẵn qua Claude Code (host) | [docs/vendors/claude.md](docs/vendors/claude.md) |
| **Codex** | Cài Codex CLI → `codex login` | [docs/vendors/codex.md](docs/vendors/codex.md) |
| **Gemini** | Cài Gemini CLI → chạy `gemini` rồi `/auth`. (Hoặc chỉ cần `GEMINI_API_KEY` cho lane API) | [docs/vendors/gemini.md](docs/vendors/gemini.md) |
| **Grok** | Cài Grok CLI → `grok` để auth | [docs/vendors/grok.md](docs/vendors/grok.md) |
| **Agy** (Antigravity) | CLI riêng, quota riêng. PolyKit **chưa** có vendor `agy` — hiện gọi nhờ trong lane 1 của `gemini` | [docs/vendors/agy.md](docs/vendors/agy.md) |
| **OpenRouter** | Lấy key **free** tại [openrouter.ai/keys](https://openrouter.ai/keys), rồi 1 trong 2: `export OPENROUTER_API_KEY=...` (Windows: `setx OPENROUTER_API_KEY ...`), **hoặc** ghi vào file `~/.config/openrouter/key` (bền, không cần export mỗi shell). Model free đổi theo mùa — xem `/polykit:watcher`, đừng hardcode | [docs/vendors/openrouter.md](docs/vendors/openrouter.md) |

**Chia việc đa vendor** (maker–checker, gate chống bịa số/sửa-theo-giả-định, luật PII):
[docs/CHIA-VIEC.md](docs/CHIA-VIEC.md).

## Mac vs Windows
- **doctor / dispatch / failover**: chạy y hệt cả hai (Python stdlib).
- **watcher tự chạy hàng tuần**: Mac dùng `launchd`, Windows dùng `schtasks` — tự chọn theo OS. Linux: chạy watcher thủ công (cron adapter chưa làm).
- Ping Telegram (failover `--send`): mặc định trỏ script của tác giả. Máy khác đặt `POLYKIT_NOTIFIER` trỏ script gửi tin của bạn, hoặc bỏ qua (chỉ hiện message).

## Nguyên tắc
- Vendor thiếu/chưa auth/hết quota → **degrade rõ ràng**, không bao giờ crash.
- Claude lane bị **giới hạn** (plan-mode, không tool) theo ToS — không dùng làm worker.
- State (cache) tự sinh; xoá được, tự tạo lại.
- **PII thật (tên/CIF/MST/số dư khách hàng) không rời Claude host** — muốn dispatch phải khử
  định danh trước. Chi tiết: `docs/CHIA-VIEC.md` §PII.
- Docs không phải nguồn sự thật về model/version — `/polykit:doctor` mới là. Số trong docs chỉ
  là snapshot có ghi ngày.

MIT. Repo: github.com/nightskat/polykit
