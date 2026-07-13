# M1a — Inventory tooling multi-vendor (2026-07-13)

> Pipeline: raw scan (Claude) → draft bảng (Gemini 3.5 Flash/agy) → adversarial review (Codex gpt-5.5, 9 findings) → chốt (Claude).
> Quyết định: **GOM** (đem vào plugin nguyên/wrap) · **PORT** (viết lại Python) · **BỎ** · **Ở-LẠI** (đúng chỗ, polykit trỏ tới).

## Bảng M1a

| Item | Quyết định | Milestone | Lý do |
| :--- | :--- | :--- | :--- |
| `cross-cli-dispatch/bin/safe-dispatch.sh` | PORT | M1c | Lõi dispatch: giữ depth-guard, timeout-guard, sandbox flags |
| `cross-cli-dispatch` (references, hooks, skills, commands) | GOM | M1b | Khung xương plugin; riêng critical path port Python ở M1c, giữ guard ToS explicit |
| Freshness engine (`refresh-state.sh`, `check-models.sh`, `lint-models.sh`, `weekly-housekeep.sh`) | GOM (wrap) | M4 | Reuse-first theo spec — KHÔNG viết engine mới, chỉ bọc adapter khi cần platformdirs |
| `quota-check.sh` (cron 4h) | PORT | M3 | Điểm quan sát ngoài session — lõi failover proactive |
| `tg-ping.sh` | PORT | M3 | Kênh alert cap/pressure; M4 reuse tiếp |
| `agy.sh` | Ở-LẠI | M1c | Gemini lane chính đang sống; dispatch.py trỏ tới khi wiring |
| Grok lane adapter (chưa tồn tại) | VIẾT MỚI | M2 | Pain 3 — adapter trong dispatch.py, binary grok chỉ là dependency |
| Grok binary (`~/.grok/bin/grok`) | Ở-LẠI | M2 | Dependency ngoài, detect qua `shutil.which` |
| `state.json` (runtime data hiện tại) | BỎ (data) / PORT (schema) | M1b–M3 | State là cache regenerate được; schema mới: `schema_version` + vendor state machine + platformdirs |
| `cross-vendor-review` (pure markdown) | GOM | M1b | Skills/references review, không có binary |
| `model-intelligence` (traits.json, bench) | GOM | M1b | Traits metadata + bench, platform-neutral |
| `governance-engine` | GOM một phần | M3 | Chỉ lấy quota schema/governor phục vụ M3; phần vague-only BỎ |
| `ping-brief` | BỎ binary, GOM format | M3 | Trùng tg-ping; giữ notification convention nếu M3 cần |
| `tuan-method/scripts/safe-dispatch.sh` | BỎ | — | Bản cũ, trùng cross-cli-dispatch/bin |
| `tuan-method` + `tuan-build-method` (doctrine) | BỎ khỏi polykit | — | Doctrine đã thay bằng `~/.claude/rules/` — rules Ở-LẠI, không đem vào plugin |
| `~/.claude/rules/routing-summary.md` (+ .ref) | Ở-LẠI | — | Doctrine routing, không phải code |
| `gem.sh`, `ask-gemini-*.sh`, `ask-sonnet.sh` | BỎ | — | Wrapper ad-hoc, CLI retired |
| `quota-check.sh.bak.*`, log/lock (`trait-errors.log`, `traits.lock`, `lint-last.json`) | BỎ | — | Backup + file tạm |
| `vendor-routing-autocheck.sh` / `-reminder.sh` | BỎ | — | Routing check cũ 05/2026, thay bằng doctor.py |
| `~/.claude/daemon/dispatch` + roster.json | BỎ | — | Daemon cũ, đã archive từ hard-reset 05/05 |
| `vague-engine`, `meo-channel`, `meo-morning` | Ở-LẠI (ngoài scope) | — | Plugin riêng, không thuộc core multi-vendor |
| Scripts không liên quan vendor (sync, backup, cleanup, jules...) | BỎ | — | Ngoài scope |

## Rủi ro / thiếu sót (input cho M1b)

- `state.json` hiện **chưa có `schema_version`** và chưa tách `not_authed`/`quota_capped` (chỉ có `available` bool + `last_error`) — vi phạm P2, M1b phải thiết kế schema mới.
- Port bash→Python phần depth-guard/sandbox flags phải giữ nguyên hành vi — guard chống rewrite-hố: M1c >3 session → wrap bash trước.
- Cấm bash critical path nghĩa là quota-check/state-write đều viết lại Python ở M3 — không copy logic bash sang nửa vời.
- ToS guard matrix (`guard.allowed[]` trong state.json) phải chuyển thành **negative test** ở M1b (P3).

## Findings Codex đã áp (9/9)

P1: tg-ping M4→M3 · freshness engine PORT→GOM-wrap (reuse-first) · agy.sh M2→M1c · thêm item Grok lane adapter M2 · state.json tách data/schema.
P2: governance-engine gom một phần · ping-brief giữ format · tách tuan-* scripts vs doctrine · cross-cli-dispatch ghi rõ ràng buộc ToS.
