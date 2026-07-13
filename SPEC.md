# POLYKIT v0.1 — Spec gọn

> Thu từ POLYHARNESS v0.1 (2026-07-13). Triết lý giữ nguyên: contract chuẩn,
> recommendation-không-ép, CLI-first. Cách build đổi: GOM đồ có sẵn, không viết platform.

## Mục tiêu
Một repo installable gom toàn bộ multi-vendor tooling (dispatch, quota, state,
traits) — cài máy mới <30 phút, vendor thiếu không lỗi.

## 5 pain gốc
1. Công cụ rời rạc 4 chỗ (~/.claude, ~/Claude/scripts, plugins, cache)
2. Không có cập nhật vendor info tự động
3. Grok chưa có lane dispatch
4. Hết quota Claude = ngồi chơi (xảy ra đúng lúc cao điểm — session nặng đốt quota)
5. Untransferable — không cài được cho người khác

## Nguyên tắc thiết kế

### P1. Graceful degradation (QUAN TRỌNG NHẤT)
- Vendor absent = state `not_installed`, KHÔNG phải error.
- Mọi command chạy được với 1 vendor duy nhất.
- `polykit doctor` in bảng: vendor | installed | authed | models | quota-state.
- Dispatch tự filter lane theo vendor available. Thiếu agy/grok → im lặng bỏ qua lane đó.
- Install.sh: detect-only, không cài vendor hộ, chỉ báo "muốn thêm X thì làm Y".

### P2. Config ≠ State
- `config/` (template, commit được, transfer được) tách khỏi `state/` (cache, quota, máy-riêng).
- Máy ông anh: copy config template, state tự sinh.

### P3. ToS hard limit
- Claude worker lane = bounded (plan-mode, no tools). KHÔNG vendor nào spawn Claude full.
- Codex/Gemini main → chỉ gọi Gemini/Grok/OR làm worker.

### P4. Task + result contract (kế thừa POLYHARNESS §7-8)
- Task: YAML (objective, expected_output, permissions, timeout).
- Result: JSON (status, summary, findings+evidence, usage, warnings).
- v0.1 chỉ cần dispatch đọc/ghi được format này — chưa cần enforce toàn bộ.

## Milestones

### M1 — Gom + đóng gói (pain 1, 5)
- Repo `~/Developer/polykit/` gom: cross-cli-dispatch, quota-check.sh, tg-ping.sh,
  freshness engine (state.json logic), traits.json schema.
- `install.sh` idempotent: symlink/copy vào đúng chỗ, detect vendor, in bảng doctor.
- Config template + README setup 1 trang.
- ✅ Acceptance: cài máy sạch (hoặc máy ông anh) <30 phút, chỉ có Claude+Codex vẫn chạy.

### M2 — Grok lane (pain 3)
- Thêm grok adapter vào dispatch (grok đã có trong state.json).
- Lane routing: grok = adversarial/đập ý tưởng (theo 4-vendor rotation).
- ✅ Acceptance: `/dispatch grok <task>` chạy; máy không có grok → lane ẩn, không lỗi.

### M3 — Quota failover (pain 4)
- Detect Claude 5h cap (exit code / error pattern) → tg-ping ngay:
  "Claude cap đến HH:MM. Lane thay thế: codex main / gemini worker."
- Playbook `SWITCH-MAIN.md`: 5 bước đổi sang Codex main khi Claude down.
- ✅ Acceptance: giả lập cap → nhận Telegram trong 1 phút, playbook chạy được thật 1 lần.

### M4 — Watcher nhẹ (pain 2)
- Cron tuần: diff model list + CLI version (mở rộng housekeep CN hiện có).
- Đổi version/model → tg-ping 1 dòng + đánh dấu stale trong state.json.
- ✅ Acceptance: bump version giả → nhận cảnh báo.

## PARKED (mở lại khi pain lặp ≥3 lần)
Quota ledger/reservation · benchmark onboarding tiers · docs snapshot diff ·
update canary · recommendation scoring engine · MCP server riêng · SQLite.

## Không làm (kế thừa non-goals POLYHARNESS)
Auto-merge · auto-deploy · DAG tự trị · multi-machine · web dashboard · billing.

## Thứ tự & nhịp
M1 → M3 → M2 → M4 (failover trước grok — pain đau hơn).
Nhịp: 1 milestone / 1-2 session, cap 45-60 phút/ngày. KHÔNG gộp 2 milestone 1 session.
