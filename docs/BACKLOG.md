# PolyKit — Backlog tham khảo

> Repo/ý tưởng để mở khi PARKED items được kích hoạt (pain lặp ≥3 lần).
> KHÔNG phải cam kết build — là kho tham khảo có chủ đích.

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
