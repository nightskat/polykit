HỎNG 2 CHỖ
PY=`~/.pyenv/versions/3.11.8/bin/python` · `$PY -m pytest tests/ -q` → `152 passed in 17.66s` **EXIT 0**. 7/7 `--dump-config` **EXIT 0**. `git diff --quiet config/vendors.json; echo $?` → `0`. `grep -n dry-run commands/failover.md` → dòng 3,6,8. `--help`=`{agy,dsh,grok,codex,gemini,claude,openrouter}`.

## Phát hiện mới — do bản vá / báo cáo (nặng → nhẹ)

| # | Mức | Lỗi | Lệnh + output thật + exit |
|---|---|---|---|
| 1 | 🟠 | Việc 2 (`not_installed` thôi bịa) **không bị test khoá**. 3 test đã chuyển chỉ khoá ok / in-trùng / headless. Gỡ `finalize` trên nhánh skip + `served=model` → 3 test + cả `test_vong6.py` vẫn xanh. | Tạm trả `DispatchResult(... served_model=None if model=="auto" else model)` không qua `finalize` → `$PY -m pytest tests/test_vong5.py::test_lenh_... tests/test_vong6.py tests/test_dispatch_v2.py::TestVong2::test_dynamic_vendor_from_json -q` → `7 passed in 0.86s` **EXIT 0**. Restore xong. |
| 2 | 🟠 | Báo cáo khai `python one_off.py` cho 4 nhánh. `python` trần **không chạy** (6 vòng liền). Kết quả 4 nhánh **đúng** khi chạy `$PY one_off.py` — gõ lại lệnh, không dán. | `python one_off.py` → `pyenv: python: command not found` **EXIT 127**. `$PY one_off.py` → no-flag 4 nhánh `served_model=None` + warning; with-flag 4 nhánh `served=fake-4.6` `warnings=[]` **EXIT 0**. |

## Việc giao vòng 11 — đã hết (runtime)

| Việc | Lệnh | Nay |
|---|---|---|
| Inject 1 dòng warning → `test_vong7` ĐỎ | thêm `stderr.write` trong `finalize` | `Expected exactly 1 warning, got 2` **EXIT 1**. Restore: `$PY -m pytest tests/test_vong6.py -q` → `5 passed in 0.56s` **EXIT 0** |
| Bẻ `served=model` luôn → `test_lenh` ĐỎ | `served = model` | `assert 'fake-model' is None` **EXIT 1** |
| Bẻ bỏ `headless` → `test_dynamic` ĐỎ | `cmd = "echo hardcoded"` | `assert "...fakebin run..." in 'echo hardcoded'` **EXIT 1** |
| Fake no-flag cả 4 nhánh | `$PY one_off.py` | ok/error/quota/not_installed: `served=None` + 1 warning «không nhận cờ» |
| Fake có-cờ cả 4 nhánh | `$PY one_off.py` | 4 nhánh `served=fake-4.6`, `warnings=[]` (quota có `'insufficient credit'`) |
| Fake **không** vào JSON | `grep fakevendor config/vendors.json; echo $?` | trống **EXIT 1**. `git diff --quiet` → `0` |
| `dry-run` còn | `grep -n dry-run commands/failover.md` | 3 dòng **EXIT 0** |
| 7 dump | `$PY bin/dispatch.py $v --dump-config` | 7/7 **EXIT 0**. `dsh` `resolved_model=deepseek-v4-pro` |

## 🧊 Phạm vi + báo cáo maker

| Kiểm | Kết quả |
|---|---|
| `git diff --stat` | **5 file**: `dispatcher.py` + `conftest.py` + 3 test. **Trong** 2 việc. Không đụng README/CLAUDE/`commands/`/`vendors.json` |
| File rơi | `one_off.py` untracked (script đo, không trong `--stat`) |
| Có **HÀNH VI ĐÃ ĐỔI** | **CÓ** — `finalize()` + `not_installed` `served=None`. Khớp diff |
| Có **PHÁT HIỆN THÊM** | **CÓ** — ghi «không phát hiện». Không khai lỗ #1 |
| `152 passed in 9.75s` | số test **KHỚP**. thời gian **LỆCH** (tôi `17.66s`, cổng `10.36s`) |
| `5 passed in 0.35s` | số **KHỚP**. thời gian **LỆCH** (`0.56s`) |
| `python` trần / dispatch thiếu prompt | **CÒN** `python one_off.py` (EXIT 127). Pytest thì dùng `$PY` |

Không sửa code / không sửa `vendors.json`. Inject/revert đã restore — `git diff --stat` lại đúng 5 file như lúc QA vào.
