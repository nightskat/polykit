# POLYKIT v0.1.1 — Spec

> Thu từ POLYHARNESS v0.1 (2026-07-13). Triết lý giữ: contract chuẩn, recommendation-không-ép.
> v0.1.1: vá 12 findings Codex review + đổi hình dạng sang **Claude Code plugin, Python-first, cross-platform**.

## Mục tiêu
Một **Claude Code plugin** gom toàn bộ multi-vendor tooling (dispatch, quota, failover, watcher).
Cài máy mới = `claude plugin marketplace add` + `install` (<30 phút kể cả auth vendor).
Chạy được trên macOS / Windows / Linux. Vendor thiếu không lỗi.

## 5 pain gốc
1. Công cụ rời rạc 4 chỗ (~/.claude, ~/Claude/scripts, plugins, ~/.cache/cross-cli)
2. Không có cập nhật vendor info tự động
3. Grok chưa có lane dispatch
4. Hết quota Claude = ngồi chơi — xảy ra đúng lúc cao điểm (session nặng đốt quota)
5. Untransferable — không cài được cho người khác (máy ông anh: OS bất kỳ)

## Hình dạng
```
polykit/  (git repo = marketplace luôn)
├── .claude-plugin/plugin.json
├── skills/          # markdown — platform-neutral
├── commands/        # /polykit:doctor, /polykit:dispatch, ...
├── bin/             # Python 3.11+ (pathlib, KHÔNG bash trên critical path)
│   ├── doctor.py  dispatch.py  quota.py  failover.py  watcher.py
│   └── platform/  # scheduler adapter: launchd|cron|schtasks
├── config/          # template, commit được (P2)
└── tests/           # fixtures + matrix test (P1)
```
State máy-riêng sinh ở `~/.polykit/state/` — KHÔNG nằm trong repo.

## Nguyên tắc

### P1. Graceful degradation — testable (Codex #1, #2, #5)
Vendor state machine: `not_installed` → `installed_not_authed` → `ready` → `quota_capped`.
- `installed_not_authed` → doctor + dispatch in hướng dẫn auth cụ thể ("chạy `codex login`"), KHÔNG lỗi.
- Bỏ lane KHÔNG im lặng: warning vào result JSON + doctor hiển thị lý do (Codex #5).
- **Ma trận acceptance** (test bằng fixture, mock detect):

| Command \ Combo | 0 vendor | Claude-only | Codex-only | Gemini-only | có not_authed |
|---|---|---|---|---|---|
| doctor | bảng đầy đủ | ✓ | ✓ | ✓ | ✓ + auth hint |
| dispatch | lỗi mềm + hint | lane bounded | ✓ | ✓ | skip + warning |
| quota | "no data" | ✓ | ✓ | ✓ | ✓ |
| watcher | no-op + log | ✓ | ✓ | ✓ | ✓ |

### P2. Config ≠ State — có schema (Codex #6)
- `config/` trong plugin (template) · state ở `~/.polykit/state/` · mỗi file JSON có `schema_version`.
- Đổi schema → bump version + migrate hoặc regenerate (state là cache, regenerate được).
- Transfer = cài plugin + copy config, state tự sinh.

### P3. ToS hard limit — có negative test (Codex #3)
- Claude lane duy nhất được phép: bounded (plan-mode, no tools, no session persistence).
- **Negative test bắt buộc**: fixture chứng minh dispatch không bao giờ sinh lệnh spawn Claude full-worker.
- Codex/Gemini main → chỉ gọi Gemini/Grok/OR làm worker.

### P4. Task + result contract — minimal nhưng enforce (Codex #7)
- Task YAML required: `objective, expected_output, timeout`. Malformed → lỗi rõ ràng, không chạy.
- Result JSON required: `status, summary, warnings[]`. Vendor bị skip → degraded result
  `{status:"skipped", reason:"not_authed|not_installed|quota_capped"}` — cùng schema, không null.

### P5. Cross-platform (mới — quyết định 13/07)
- Python 3.11+ cho mọi logic; `pathlib` + `platformdirs`, cấm hardcode `/Users/...`.
- Scheduler qua adapter: launchd (mac) / cron (linux) / schtasks (win). Chỉ adapter được biết OS.
- Vendor CLI: tự detect (`shutil.which`), chưa auth → nhắc lệnh auth. Plugin KHÔNG cài CLI hộ.
- CI matrix 3 OS (GitHub Actions) chạy tests/ — thay cho "test trên máy ông anh".

## Prereqs công khai (Codex #12)
README liệt kê: git, Python 3.11+, Claude Code. Vendor CLIs = optional, mỗi cái 1 dòng
"cài + auth thế nào". Lời hứa 30 phút tính CẢ auth 2 vendor đầu.

## Milestones

### M1 — Plugin skeleton + doctor (pain 1, 5) — tách 3 bước (Codex #8)
- **M1a Inventory**: quét 4 chỗ tooling hiện có → bảng "gom gì, bỏ gì, port gì". 1 session, chỉ đọc.
- **M1b Skeleton + doctor.py**: plugin.json, cấu trúc repo, doctor với vendor state machine
  + ma trận P1 chạy trên fixture. Acceptance: cài plugin máy hiện tại, doctor đúng 100% ma trận.
- **M1c Port dispatch.py**: port safe-dispatch.sh sang Python (giữ depth-guard, timeout-guard,
  sandbox flags). Acceptance: dispatch codex + gemini chạy thật; combo thiếu vendor ra degraded result.

### M3 — Quota failover (pain 4) — fixture hoá (Codex #9)
- Capture stderr/exit-code THẬT của Claude 5h cap → lưu `tests/fixtures/claude_cap.txt`.
- Detect match fixture → tg-ping "Cap đến HH:MM. Lane thay thế: codex main / gemini worker."
- Unknown error ≠ cap → log, KHÔNG ping (chống báo động giả).
- Playbook `SWITCH-MAIN.md` 5 bước. Acceptance: replay fixture → ping <1 phút; error lạ → im.

### M2 — Grok lane (pain 3) — acceptance đủ (Codex #11)
- Grok adapter trong dispatch.py: state.json entry, timeout, result JSON chuẩn P4, evidence log.
- Acceptance: dispatch grok chạy; máy không grok → degraded result + doctor ghi rõ; 402 → `quota_capped` không phải crash.

### M4 — Watcher nhẹ (pain 2) — có guards (Codex #10)
- Weekly qua scheduler adapter: diff model list + CLI version → đánh dấu stale + tg-ping 1 dòng.
- Guards: timeout mọi lệnh detect · máy offline/ngủ → skip im lặng, chạy bù lần sau ·
  auth hết hạn → state `not_authed` (không alert lặp) · file lock chống race với dispatch.
- Acceptance: bump version giả → 1 alert duy nhất; rút mạng → không crash không spam.

## PARKED (mở lại khi pain lặp ≥3 lần)
Quota ledger/reservation · benchmark onboarding tiers · docs snapshot diff · update canary ·
recommendation scoring · MCP server riêng · SQLite · auto-cài vendor CLI.

## Không làm
Auto-merge · auto-deploy · DAG tự trị · multi-machine · web dashboard · billing.

## Thứ tự & nhịp
M1a → M1b → M1c → M3 → M2 → M4. Mỗi bước 1 session, cap 45-60 phút/ngày, không gộp.
