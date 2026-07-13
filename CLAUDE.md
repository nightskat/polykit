# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Trạng thái hiện tại

**v0.1 code hoàn chỉnh — 6/6 milestone xong (M1a→M1b→M1c→M3→M2→M4).** 65 test pass.
Đọc `SPEC.md` (v0.1.2) cho scope/nguyên tắc, `docs/M1A-INVENTORY.md` cho quyết định gom tooling.

### Chạy
```
python bin/doctor.py            # trạng thái vendor (state machine)
echo "prompt" | python bin/dispatch.py <codex|gemini|claude|grok> [model] --result-json
python bin/failover.py --pressure 85     # quota failover proactive/reactive
python bin/watcher.py --dry-run          # diff model/version weekly
~/.pyenv/versions/3.11.8/bin/python -m pytest tests/ -q   # 65 test
```

### Map module → milestone
| Milestone | File chính | Acceptance đã đạt |
|---|---|---|
| M1b doctor | `bin/doctor.py`, `bin/lib/{states,vendors,state_store}.py` | detect 4 vendor, state.json schema_version=1 |
| M1c dispatch | `bin/dispatch.py`, `bin/lib/{dispatch_core,dispatcher}.py` | codex+gemini chạy thật, thiếu vendor→skipped, ToS negative test |
| M3 failover | `bin/failover.py`, `bin/lib/{quota,handoff,notifier}.py` | pressure→ping trước, cap→ping reactive, lỗi lạ→im |
| M2 grok | `bin/lib/{quota_error,evidence}.py` (+dispatcher) | 402→quota_capped không crash, evidence log |
| M4 watcher | `bin/watcher.py`, `bin/lib/watcher.py`, `bin/platform/launchd.py` | bump→1 alert, offline→skip, notify fail→retry |

## Dự án là gì

PolyKit = **Claude Code plugin** gom multi-vendor CLI tooling (dispatch, quota failover, watcher) thành 1 repo cài được trên máy mới (<30 phút, mọi OS). Repo này đồng thời là plugin marketplace. Second Brain home: `~/Claude/Projects/polykit/`.

## Kiến trúc đích (theo SPEC.md)

- `bin/` — Python 3.11+ cho MỌI logic (doctor, dispatch, quota, failover, watcher). **Cấm bash trên critical path.**
- `skills/`, `commands/` — markdown, platform-neutral (`/polykit:doctor`, `/polykit:dispatch`, ...).
- `config/` — template, commit được. **State máy-riêng KHÔNG nằm trong repo** — path do `platformdirs` quyết định.
- `tests/` — pytest với fixtures + mock detect; chạy local trên mac (CI matrix 3 OS = PARKED).

## Nguyên tắc bất di bất dịch (P1–P5)

1. **Graceful degradation**: vendor state machine `not_installed → installed_not_authed → ready → quota_capped`. Vendor thiếu KHÔNG gây lỗi, KHÔNG bị skip im lặng — warning vào result JSON. Có ma trận acceptance trong SPEC.md phải test bằng fixture.
2. **Config ≠ State**: mỗi file JSON có `schema_version`; state là cache, regenerate được.
3. **ToS hard limit**: Claude lane duy nhất = bounded (plan-mode, no tools). Bắt buộc có negative test chứng minh dispatch không bao giờ spawn Claude full-worker.
4. **Contract enforce**: Task YAML required `objective, expected_output, timeout`; Result JSON required `status, summary, warnings[]`. Vendor skip → degraded result cùng schema, không null.
5. **Cross-platform bằng thiết kế**: `pathlib` + `platformdirs`, cấm hardcode `/Users/...`. Subprocess đơn giản (`subprocess.run(timeout=)`, không PID tree/signal Unix). Detect vendor bằng `shutil.which`, lưu absolute path vào state.

## Thứ tự milestones

M1a (inventory, chỉ đọc) → M1b (skeleton + doctor.py) → M1c (port dispatch.py) → M3 (quota failover proactive) → M2 (Grok lane) → M4 (watcher). **Mỗi bước 1 session, không gộp.** Guard M1c: quá 3 session chưa xong → dừng port, wrap bash hiện có trước.

## Nguồn tooling sẽ gom (cho M1a)

4 chỗ hiện tại: `~/.claude/`, `~/Claude/scripts/` (quota-check.sh, tg-ping.sh), `~/Developer/plugins/tuan-*`, `~/.cache/cross-cli/` (state.json + freshness engine — M4 mở rộng cái này, KHÔNG viết engine mới).
