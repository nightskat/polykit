HỎNG 4 CHỖ
PY=`~/.pyenv/versions/3.11.8/bin/python` · `$PY -m pytest tests/ -q` → `152 passed in 12.06s` **EXIT 0** · 11/11 `--dump-config` **EXIT 0**.

## Phát hiện mới — do bản vá đẻ (nặng → nhẹ)

| # | Mức | Lỗi | Lệnh + output thật + exit |
|---|---|---|---|
| 1 | 🔴 | `CLAUDE.md` đổi `$PY -m pytest` (chạy được) → `python3 -m pytest`. `python3` = 3.14.7, không có pytest. Maker khai `152 passed in 11.53s` EXIT 0. | `python3 -m pytest tests/ -q` → `/opt/homebrew/opt/python@3.14/bin/python3.14: No module named pytest` **EXIT 1**. `$PY -m pytest tests/ -q` → `152 passed in 12.06s` **EXIT 0**. |
| 2 | 🔴 | Khối lệnh `CLAUDE.md` copy-paste được: `echo "prompt" \| python3 bin/dispatch.py <agy\|dsh\|…\|openrouter> [model] --result-json`. zsh hiểu là pipeline, **bật CLI thật** (goose panic, dsh thiếu `--profile`, gemini, …). | Cùng lệnh nguyên văn → `(eval):3: no such file or directory: agy` / `command not found: openrouter` / `thread 'goose-cli-main' panicked` / `error: --profile <name> is required` / `No input provided via stdin` **EXIT 127**. |
| 3 | 🟡 | README + `commands/failover.md` bảo mặc định `--dry-run`, thêm `--send`. CLI **không có** `--send`. Không gắn `--dry-run` thì **gửi Telegram thật**. `CLAUDE.md` đúng lệnh đó. | `python3 bin/failover.py --send --pressure 85` → `unrecognized arguments: --send` **EXIT 2**. `python3 bin/failover.py --pressure 85 --dry-run` → `notified: false, dry_run: true` **EXIT 0**. `--help` không có `--send`. |
| 4 | 🟡 | Soát docs nửa vời: `/polykit:dispatch` còn 5 vendor; `doctor.py` chỉ REGISTRY (7); schema README thiếu field bắt buộc. | `commands/dispatch.md` description = `codex\|gemini\|claude\|grok\|openrouter`. `python3 bin/doctor.py` **EXIT 0** in 7 dòng (codex…dsh), không có opencode/goose/zeroclaw/jules. README liệt kê 11 + «mọi vendor». Schema không có `binary` / `default_model` / `verify_cmd` / `model_override`. CLAUDE.md bảng M1b còn `detect 4 vendor`. README `Python 3.9+` vs SPEC/CLAUDE `3.11+`. |

## 2 việc vòng 6 — đã hết

| Việc | Lệnh | Nay |
|---|---|---|
| Warning trùng text | `printf hi \| FAKE_OC_FAIL=1 PATH="/tmp/pk-fakebin:$PATH" $PY bin/dispatch.py opencode --no-traps --allow-unknown-model --timeout 5` | stderr 1 lần `[polykit] warning: vendor 'opencode' không nhận cờ model…` rồi `ERROR:` / `Warnings:` / `  - boom: fake fail`. stdout trống. **EXIT 1**. `grep -c` = **1**. |
| Vẫn thấy ở text | cùng fake, nhánh ok / quota | ok: stdout `fake ok output`, stderr 1 warning **EXIT 0**. quota: 1 warning + `ERROR: …quota-capped` **EXIT 1**. |
| `--result-json` 1 lần | thêm `--result-json` | stderr 1 dòng warning. JSON `warnings` có câu đó (dữ liệu, không in đôi). `served_model: null` **EXIT 1**. |
| Revert → đỏ | cắt filter, chạy `test_vong7_text_duplicate_warning`, hoàn nguyên | revert: `got 2` **1 failed in 0.14s EXIT 1**. restore: `1 passed in 0.12s EXIT 0`. `diff` file = trống. |

## Lệnh trong BAO-CAO-VONG7.md

| Lệnh họ ghi | Đối chiếu |
|---|---|
| `$PY … opencode --no-traps …` (có `printf hi`) | **KHỚP** text 1 warning + `boom: fake fail` **EXIT 1**. JSON 1 lần. **Không** còn `python` trần. **Có** prompt. |
| `python3 bin/doctor.py` | **KHỚP EXIT 0**. Bảng 7 vendor (REGISTRY), không phải «7 cái có verify_cmd». |
| `printf "hi" \| python3 bin/dispatch.py codex --result-json` | **KHỚP EXIT 0**. Tôi chạy đúng README (`printf "prompt"`) → `status=ok model=served=gpt-5.6-terra stdout="How can I help?\n"`. Họ ghi `"Hi! What would you like to work on?"` — prompt khác. |
| `python3 bin/failover.py --pressure 85` → `notified: true` | **KHỚP kiểu lệnh** (không `--dry-run` = gửi thật). Tôi không gửi lần nữa. `--dry-run` → `notified: false`. |
| `python3 bin/watcher.py --dry-run` → `agy ready→auth_unverified; agy -14 models` | **LỆCH**. Thực tế `{"action":"noop","reason":"no_change","dry_run":true}` **EXIT 0**. Số/chuỗi từ lần chạy cũ. |
| `python3 -m pytest tests/ -q` → `152 passed in 11.53s` | **KHÔNG CHẠY ĐƯỢC** (mục #1). Số 152 chỉ đúng với `$PY`. Thời gian họ `11.53s` / tôi `12.06s`. |

## 11 dump-config (model mặc định)

agy/dsh/grok/codex/gemini/claude/opencode/goose/zeroclaw/jules/openrouter — **cả 11 EXIT 0**. dsh `resolved=deepseek-v4-pro` (không flash).

Không sửa code / không sửa `vendors.json`.
