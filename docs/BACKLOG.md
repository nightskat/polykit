# PolyKit — Backlog tham khảo

> Repo/ý tưởng để mở khi PARKED items được kích hoạt (pain lặp ≥3 lần).
> KHÔNG phải cam kết build — là kho tham khảo có chủ đích.

## Việc của chính PolyKit

### ✅ XONG 2026-08-03 (v0.4.0) — Tách `agy` (Antigravity) thành vendor riêng
Hiện `agy` bị nhét làm lane 1 của vendor `gemini`, nhưng nó là **CLI độc lập**: binary riêng
(`~/.local/bin/agy` v1.1.9), quota riêng, inventory riêng — 11 slug gồm cả `claude-sonnet-4-6`,
`claude-opus-4-6-thinking`, `gpt-oss-120b-medium` (xem `vendors/agy.md`).

Hệ quả của việc nhét chung:
- `doctor` mù với agy — agy chết chỉ thấy dispatch gemini âm thầm tụt lane.
- 3 model không-Gemini của agy **không gọi được** qua `/polykit:dispatch` (`is_agy_model()`
  chỉ nhận slug `gemini-*`).
- `watcher` không diff được catalog agy → 3.6 vào/ra không ai báo.

Đã làm đúng như dự kiến + `models_cmd` để catalog vào state.json. Còn hở, ghi lại để khỏi quên:
- `codex`/`grok` chưa có `models_cmd` → cột "Số model" trong SNAPSHOT.md để `—`.
  `codex debug models` trả JSON (parse_models chỉ hiểu dòng-slug), `grok models` in banner.
- launchd bỏ lỡ lịch khi máy TẮT hẳn qua thứ 2 12:00 → chạy bù lúc boot, nhưng nếu tắt cả
  tuần thì mất một kỳ. Chưa có cơ chế "quá hạn N ngày thì chạy ngay".

## Repos tham khảo

### OpenUsage — `github.com/robinebers/openusage` (MIT, Swift, 3k★)
App menu-bar macOS track quota 10 provider (Claude, Codex, Copilot, Cursor, Devin,
Grok, Antigravity, OpenCode, OpenRouter, ZAI). **Bổ trợ, không đối thủ**: nó = GUI hiển thị,
PolyKit = CLI điều phối/failover.

**Cơ chế đáng học (đã verify qua README 2026-07-13):**
- Đọc **local credentials** (keychain / auth files / app state) cho hầu hết provider — KHÔNG parse stderr.
- Đọc **local CLI logs** (Claude/Codex/Grok) cho spend Today/30d.
- OpenRouter + ZAI cần API key thủ công (không có local credential).
- Kiến trúc: `auth store → usage client → mapper → ProviderSnapshot`.

**3 thứ lấy được (khi mở PARKED):**
1. **Vá điểm yếu M3**: thay stderr-parsing cap-detect bằng đọc structured quota từ
   local creds/logs của Claude/Codex → pressure % proactive thật. (Codex đã chê M3 điểm này.)
2. **Mở REGISTRY 4→10 vendor**: mapper pattern của nó = bản Swift của `snapshot_from_state`
   (M4). Thêm Copilot/Cursor/OpenRouter theo cùng khuôn `VendorProbe`.
3. **Reset countdown / reset banks**: metric PolyKit chưa có, hợp M3 proactive.

**Không lấy**: GUI Swift, spend dashboard (ngoài scope).

## Repos hỗ trợ — theo mảnh PolyKit (tìm 2026-07-13)

### 🎯 Reuse cao nhất — M3 quota (vá stderr-parsing)
- **coding_agent_usage_tracker (CAUT)** `Dicklesworthstone/coding_agent_usage_tracker` —
  1 CLI đọc quota 16+ provider, xuất **JSON/Markdown cho AI agent tiêu thụ**. → PolyKit M3
  có thể SHELL OUT sang CAUT lấy structured quota thay vì parse stderr. **Ứng viên reuse số 1.**
- **Claude-Code-Usage-Monitor** `Maciek-roboblog` — real-time + predictions/warnings.
  Tham khảo cơ chế proactive-predict cho ngưỡng pressure.
- **TokenTracker** `mm7894215` / **tokscale** `junhoyeo` — dedup token đa provider + reset countdown.

### 🔀 M1c dispatch — cùng hình dạng, đối chiếu contract
- **agent-mux** `buildoak/agent-mux` — "one CLI, one JSON contract, unified output" cho
  Codex/Claude/Gemini. **Gần như PolyKit dispatch.py** → so `DispatchResult` với JSON contract của họ.
- **sub-agents-skills** `shinpr` — route task tới Codex/Claude/Cursor/Gemini dạng Agent Skills.
- **vnx-orchestration** `Vinix24` — governance-first, receipts, quality gates, `vnx dispatch-agent`
  (gần cả stack cross-vendor-review + dispatch của Tuan).

### 🔄 M3 failover — thiết kế fallback (khác lớp: API, không phải CLI-sub)
- **LiteLLM** router — chuẩn vàng fallback 429/5xx→provider kế, cooldown Redis, RPM/TPM.
  Học **taxonomy**: general / content_policy / context_window fallbacks. (API-level, không CLI-subscription.)
- **llm-fallback-router** (Python) — failover explicit + auditable log. Khớp triết lý evidence-log của mình.

### 📋 M3 handoff — bản giàu hơn note zero-dep
- **cli-continues** `yigitkonur/cli-continues` — CHÍNH là `continues` CLI mà SPEC/memory PolyKit
  nhắc là optional [[reference_continues_cli]]. Resume session sang tool khác.
- **CASR** `Dicklesworthstone/cross_agent_session_resumer` — canonical IR, switch model mid-task,
  **recover từ provider outage** = đúng ca Claude cap→codex của M3. Giàu hơn markdown note.
- **Continue Later** — ghi handoff file ở repo root (git state, tasks, gotchas, run commands).
  Tham khảo FIELD cho `build_handoff_note`.

### 🧭 Meta — tự tìm tiếp
- **awesome-cli-coding-agents** `bradAGI` — directory harness/orchestrator, quét khi cần thêm.

## Còn treo sau chuỗi 12 vòng (17/08/2026)

Chuỗi `maker agy → QA Grok → cổng script` chạy 12 vòng, vòng 12 QA kết luận
`KHÔNG TÌM RA CHỖ HỎNG`. Những mục dưới đây **cố ý chưa làm**, không phải bỏ sót.

### Đề xuất của maker, chờ chủ dự án quyết
- ⚖️ **`bin/failover.py` có nên mặc định `--dry-run`?** Hiện thiếu cờ là **gửi Telegram thật**.
  Plugin (`commands/failover.md`) đã gắn `--dry-run` cứng nên `/polykit:failover` an toàn,
  nhưng gọi CLI trực tiếp thì dễ gây tai nạn. Đổi mặc định là **đổi hành vi** → cần người ký.

### Chưa đủ đau để làm
- `openrouter` sống trong REGISTRY cũ, chưa có mục trong `config/vendors.json` (v3).
  Dispatch được, nhưng không ghim được model theo danh sách.
- `gemini` là vendor duy nhất còn `models: {}` + `CHUA_KIEM` (danh sách model, quota).
  Khảo sát lượt 17/08 bị timeout vì chính CLI gemini treo.

### Bài học vận hành đã ghi vào memory (không lặp lại)
- Vé vào `vendors.json` = **đã làm được việc thật**, không phải "máy có cài".
  `opencode`/`goose`/`zeroclaw` là **lớp vỏ** gọi OpenRouter → đã gỡ.
- Maker có trait **reward hacking**: bẻ hành vi cho khớp test/tài liệu.
  → Đề bài phải nêu **ràng buộc**, không chỉ định giải pháp; và mọi thứ có
  **hậu quả ra ngoài** (gửi tin, gọi API) phải có **phép đo riêng trong cổng chặn**.
- Test remap sang **vendor thật** là mất tác dụng (3 vòng lặp cùng lỗi).
  → Dùng **vendor giả trong `tests/conftest.py`**.
- Điều kiện nghiệm thu một bản vá: **bẻ hành vi → test phải ĐỎ**. Xanh = test rỗng ruột.

### 🔬 Cần forensic (chưa làm) — dsh qua dispatch.py ra 0 byte
17/08/2026 19:30. `dsh` chạy **trực tiếp** thì tốt suốt phiên (4 việc, $0,39, có việc 7 phút).
Nhưng gọi **qua polykit** thì im lặng:
```
export DEEPSEEK_API_KEY=$(security find-generic-password -a "$USER" -s DEEPSEEK_API_KEY -w)
$PY bin/dispatch.py dsh --no-traps < de-bai.md
→ stdout 0 byte · stderr 0 byte · không tạo file kết quả
```
Nghi ở **tầng harness/dispatch**, không ở dsh:
- Prompt đưa qua **stdin redirect từ file** (`< file`) — dispatch có đọc hết stdin không, hay chỉ đọc dòng đầu?
- `dsh --profile headless` nhận task qua **tham số dòng lệnh**, không qua stdin. `dispatch.py` có ghép đúng không?
- Có thể prompt dài (~40 dòng) bị cắt hoặc bị coi là rỗng → dsh không có việc gì làm.
- Đối chứng đã có: cùng lúc đó `dsh --profile headless "<task>"` gọi trực tiếp vẫn chạy.
👉 Cách kiểm: log lệnh thật mà `dispatch.py` dựng ra cho `dsh` (in `cmd` ra stderr), so với lệnh gọi tay chạy được.
