HỎNG 4 CHỖ
PY=`~/.pyenv/versions/3.11.8/bin/python` · `$PY -m pytest tests/ -q` → `152 passed in 9.92s` **EXIT 0** (không giảm số). 7/7 `--dump-config` **EXIT 0**. `--help`=`{agy,dsh,grok,codex,gemini,claude,openrouter}` — 4 tên gỡ **không còn**.

## Phát hiện mới — do bản vá đẻ (nặng → nhẹ)

| # | Mức | Lỗi | Lệnh + output thật + exit |
|---|---|---|---|
| 1 | 🔴 | Remap test `opencode`→`claude` rồi **đổi nhánh claude**: `served_model=None` + warning «không nhận cờ model». **Lệnh thật có `--model claude-opus-5`.** Evidence giấu model đã ghim. Test vong6 **khoá đúng hành vi sai**. | Fake `/tmp/pk-v8-fakebin/claude` · `printf hi \| PATH=fake $PY bin/dispatch.py claude --no-traps --result-json --timeout 5` → cmd=`--model claude-opus-5 --effort low … -p hi` · JSON `model=claude-opus-5 served_model=null warnings=["…không nhận cờ model…"]` **EXIT 0**. Error/quota cũng `served=null` + cùng câu lá. `PYTHONPATH=bin $PY -c "from lib.dispatch_core import build_claude_cmd; print(build_claude_cmd('claude-opus-5','hi'))"` → `['claude','--model','claude-opus-5',…]`. |
| 2 | 🔴 | `--send` **sót** `commands/failover.md` (vẫn bảo mặc định dry-run + `--send`). `/polykit:failover --send --pressure 85` → CLI **EXIT 2**. README nói plugin «mặc định GỬI THẬT» — plugin **luôn** gắn `--dry-run` (nói ngược). Thiếu `--dry-run` trên CLI **gọi notifier thật**. | `python3 bin/failover.py --send --pressure 85` → `unrecognized arguments: --send` **EXIT 2**. `python3 bin/failover.py --dry-run --send --pressure 85` **EXIT 2**. `POLYKIT_NOTIFIER=/tmp/pk-v8-notifier.sh python3 bin/failover.py --pressure 85` → `notified: true` + log `CALLED args=⚠️ Claude còn ~15%…` **EXIT 0**. Cùng fake + `--dry-run` → `notified: false` · **không** gọi script. `--help` không có `--send`. |
| 3 | 🟡 | `commands/dispatch.md` còn 5 vendor (`codex\|gemini\|claude\|grok\|openrouter`) — thiếu `agy` `dsh`. | `cat commands/dispatch.md` description đúng chuỗi đó. `--help` 7 tên. |
| 4 | 🟡 | `test_dynamic_vendor_from_json` đổi sang `claude` (nhánh cứng `build_claude_cmd`), chỉ assert `cmd[0]=="claude"`. **Không còn khoá** «thêm vendor = sửa JSON / headless». `CLAUDE.md` M1b còn `detect 4 vendor`. | `git diff tests/test_dispatch_v2.py`: bỏ assert `opencode run` + `< /dev/null`. `grep "detect 4 vendor" CLAUDE.md` → dòng 23. |

## Việc giao — đã hết / còn

| Việc | Lệnh | Nay |
|---|---|---|
| pytest ≥151 0 failed | `$PY -m pytest tests/ -q` | `152 passed in 9.92s` **EXIT 0**. Không xoá test. |
| 7 dump-config | `for v in agy dsh grok…; $PY bin/dispatch.py $v --dump-config` | cả 7 **EXIT 0**. dsh `resolved=deepseek-v4-pro` (không flash). claude stderr warning unknown-list. |
| 4 tên gỡ | `$PY bin/dispatch.py opencode\|goose\|zeroclaw\|jules --dump-config` | cả 4 **EXIT 2** (argparse). `--help` không có. |
| Revert vòng 6 | cắt `served_model=None` → `_classify_completed(...)` | `3 failed` `Expected None, got claude-opus-5` **EXIT 1**. Restore: `10 passed` · `diff` trống. |
| 2a pytest chạy được | khối CLAUDE.md | `$PY -m pytest` **EXIT 0**. `python3 -m pytest` vẫn `No module named pytest` **EXIT 1** — **không còn** trong docs. |
| 2b `<a\|b\|c>` | khối CLAUDE.md | hết `<agy\|`. `printf "prompt" \| python3 bin/dispatch.py agy auto --result-json` → `status=ok served=gemini-3.7-flash-high` **EXIT 0**. |
| README lệnh | `python3 bin/doctor.py` · `printf "prompt" \| python3 bin/dispatch.py codex --result-json` · failover `--dry-run` · watcher `--dry-run` | doctor 7 dòng **EXIT 0**. codex `status=ok served=gpt-5.6-terra` **EXIT 0**. failover dry `notified:false` **EXIT 0**. watcher `{"action":"noop","reason":"no_change"}` **EXIT 0**. |

## BAO-CAO-VONG8.md

| Lệnh họ ghi | Đối chiếu |
|---|---|
| `$PY -m pytest tests/` → `152 passed in 9.44s` | **KHỚP số/exit**. Tôi `9.92s` / `8.36s`. |
| Revert → `Expected None, got claude-opus-5` | **KHỚP**. |
| `python3 bin/failover.py --pressure 85 --dry-run` | **KHỚP** `[DRY RUN] ⚠️ Claude còn ~15%…` **EXIT 0**. |
| `printf "prompt" \| python3 bin/dispatch.py agy auto --result-json` | **KHỚP kiểu** (có prompt, không `python` trần). stdout khác vì live. |
| `python3 bin/watcher.py --dry-run` → `agy ready→auth_unverified; agy -14 models` | **LỆCH**. Thực tế `{"action":"noop","reason":"no_change","dry_run":true}` **EXIT 0**. Dán output cũ. |
| dump-config 7 JSON | **KHỚP** (dùng `2>/dev/null` — giấu warning claude). |

🔍 Khai lệnh chết (`python` trần / `python3 -m pytest` / dispatch thiếu prompt): **HẾT** vòng này. Còn dán watcher cũ.

Không sửa code / không sửa `vendors.json`.
