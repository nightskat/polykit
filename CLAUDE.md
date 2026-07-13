# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Trạng thái hiện tại

**Spec-only, chưa có code.** Đang ở trước milestone M1a (inventory). Đọc `SPEC.md` (v0.1.2) trước mọi việc — đó là nguồn sự thật duy nhất về scope, nguyên tắc, và acceptance criteria.

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
