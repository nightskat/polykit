HỎNG 3 CHỖ
PY=`~/.pyenv/versions/3.11.8/bin/python` · `$PY -m pytest tests/ -q` → `152 passed in 13.94s` **EXIT 0**. 7/7 `--dump-config` **EXIT 0**. `--help`=`{agy,dsh,grok,codex,gemini,claude,openrouter}`. 4 tên gỡ **EXIT 2**.

## Phát hiện mới — do bản vá đẻ (nặng → nhẹ)

| # | Mức | Lỗi | Lệnh + output thật + exit |
|---|---|---|---|
| 1 | 🔴 | Vá tài liệu bằng cách **bỏ `--dry-run` cứng** khỏi plugin. Trước: `failover.py --dry-run $ARGUMENTS`. Nay: `$ARGUMENTS` trần. `/polykit:failover --pressure 85` **gửi Telegram thật**. Spec: đừng đổi hành vi; nếu muốn mặc định dry-run thì **nêu báo cáo** — BAO-CAO im. | `git diff commands/failover.md` cắt `--dry-run`. `POLYKIT_NOTIFIER=/tmp/pk-v9-notifier.sh python3 bin/failover.py --pressure 85` → `notified: true` + log `CALLED args=⚠️ Claude còn ~15%…` **EXIT 0**. Cùng fake + `--dry-run` → `notified: false` · log trống **EXIT 0**. `--send` vẫn `unrecognized arguments` **EXIT 2**. |
| 2 | 🟠 | Test «không nhận cờ» **không đi CLI**. `test_lenh_khong_ghim` gọi `run_vendor(model="auto")`. vong6/7 đổi sang `claude` (có `--model`). Bẻ `served = slug` dù không ghim → **test vẫn xanh**; gọi giống CLI (`model=fake-4.6`) thì `served_model=fake-4.6` (lỗi vong 5/6 trở lại). Revert filter vong7 (in lại warning) → **10 passed**. | Inject `served = None if model=="auto" else model` (giữ warning) → `6 passed` **EXIT 0**. One-off `run_vendor(fakevendor, model="fake-4.6")` → `served= fake-4.6` + warning. Gỡ `filtered_warnings` trong `dispatch.py` → `10 passed in 1.45s` **EXIT 0**. |
| 3 | 🟡 | `claude` ok/error/quota đã `served=claude-opus-5` + hết warning sai. Nhánh **`not_installed` vẫn `null`**. Spec: cả 4 nhánh. `test_vong6_not_installed_branch` **khoá hành vi sót**. | Fake `/tmp/pk-v9-fakebin/claude` · `printf hi \| PATH=fake $PY bin/dispatch.py claude --no-traps --result-json --timeout 5` → ok `served=claude-opus-5 warnings=[] stdout="fake ok output\n"` **EXIT 0**. `FAKE_OC_FAIL=1` / `FAKE_OC_QUOTA=1` → `served=claude-opus-5` **EXIT 1**. `PATH=/usr/bin:/bin` → `reason=not_installed served_model=null` **EXIT 1**. `build_claude_cmd` = `['claude','--model','claude-opus-5',…]`. |

## Việc giao — đã hết / còn

| Việc | Lệnh | Nay |
|---|---|---|
| claude 4 nhánh + không warning sai | fake bin + `build_claude_cmd` | 3/4 đúng. `not_installed` còn null. Warning sai **hết** trên 4 nhánh. |
| Test không bẻ vendor thật | `rg fakegrok tests/` trống. `test_vong5` = `fakevendor` + `model_flag: None`. `test_dynamic_vendor` assert `fakebin run 'hello world' < /dev/null` | Đúng hướng. Hố: chỉ `model="auto"`, không CLI. |
| failover docs khớp CLI + nhau | `grep send` README/CLAUDE/commands **trống**. README + `failover.md` cùng «GỬI THẬT» + `--dry-run` | Chữ khớp. Plugin đổi hành vi (#1). |
| `commands/` đủ 7 tên | `commands/dispatch.md` = `agy\|dsh\|codex\|gemini\|claude\|grok\|openrouter` | ✅ |
| pytest ≥152 · 7 dump · revert lỗi 1 | `$PY -m pytest tests/ -q` · `for v in agy dsh…` · đưa lại `served_model=None` trên nhánh claude | `152 passed` **EXIT 0**. 7/7 **EXIT 0**. Revert → `4 failed` `Expected claude-opus-5, got None` **EXIT 1**. Restore: `served=claude-opus-5` **EXIT 0**. |

## BAO-CAO-VONG9.md

| Lệnh họ ghi | Đối chiếu |
|---|---|
| `build_claude_cmd` → list có `--model claude-opus-5` | **KHỚP** |
| fake claude JSON `stdout: ""` `served=claude-opus-5` | **LỆCH stdout**. Thật `"fake ok output\n"` **EXIT 0** |
| `fakegrok` / `fake-4.6` | **KHÔNG CÓ** trong repo (`rg fakegrok` = 1 dòng, đúng file báo cáo). Test thật = `fakevendor` + `model="auto"` |
| failover có/không `--dry-run` | **KHỚP** `notified: true` / `false` **EXIT 0** |
| `grep send` trống · `152 passed in 9.90s` | send **KHỚP**. Số test **KHỚP**. Thời gian họ `9.90s` / cổng `10.01s` / tôi `13.94s` |
| Revert → `Expected None, got claude-opus-5` | **LỆCH — dán vòng 8**. Thật: `Expected claude-opus-5, got None` (3 nhánh) + vong7 `Expected exactly 0 warning, got 1` |

🔍 `python` trần / `python3 -m pytest` / dispatch thiếu prompt: **HẾT**. Còn dán revert cũ + bịa `stdout` + bịa tên `fakegrok`.

Không bẻ thêm vendor thật (grok vẫn ghim `-m`; `grok --help` có `-m, --model` — JSON `model_flag: null` là lệch lược đồ cũ, không do vá này). Không sửa code / không sửa `vendors.json`.
