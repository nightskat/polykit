HỎNG 2 CHỖ
PY=`~/.pyenv/versions/3.11.8/bin/python` · `$PY -m pytest tests/ -q` → `152 passed in 8.49s` **EXIT 0**. 7/7 `--dump-config` **EXIT 0**. `git diff --quiet config/vendors.json; echo $?` → `0`. `--help`=`{agy,dsh,grok,codex,gemini,claude,openrouter}`. 4 tên gỡ **EXIT 2**.

## Phát hiện mới — do bản vá đẻ (nặng → nhẹ)

| # | Mức | Lỗi | Lệnh + output thật + exit |
|---|---|---|---|
| 1 | 🔴 | Vá skip gán `served_model=model` **không nhìn `model_flag`**. Cùng vendor giả `model_flag: null`: **ok** = `served=None` + warning; **not_installed** = `served=fake-4.6` + **0 warning**. Bịa slug trên đường thêm vendor JSON (README hướng dẫn). Test `test_lenh` chỉ khoá nhánh ok. | `$PY` one-off `run_vendor(fakevendor, model=fake-4.6)` + `which=None` → `status=skipped reason=not_installed served_model=fake-4.6 warnings=[]` **EXIT 0**. Cùng vendor `which=/usr/bin/true` → `served_model=None` + warning «không nhận cờ» **EXIT 0**. |
| 2 | 🟠 | `test_vong7_text_duplicate_warning` đổi sang **claude** (có `--model`) + assert `count==0`. Khoá «cảnh báo đúng 1 lần» **mất**. In trùng warning trên vendor không cờ → test vẫn xanh. | Inject thêm 1 `stderr.write` warning ở `dispatcher.py` → `$PY -m pytest tests/test_vong5.py tests/test_vong6.py -q` → `10 passed in 1.55s` **EXIT 0**. Restore: 1 lần write. |

## Việc giao vòng 9 — đã hết

| Việc | Lệnh | Nay |
|---|---|---|
| `grep -n dry-run commands/failover.md` | 3 dòng (hint + luôn `--dry-run` + lệnh) | ✅ **EXIT 0** |
| Notifier giả | CLI trần `--pressure 85` → `notified: true` + log `CALLED args=⚠️…` **EXIT 0**. `--dry-run` → `notified: false` · log trống **EXIT 0** | ✅ |
| `grep -rn send README.md commands/ CLAUDE.md` | trống | ✅ **EXIT 1** |
| Test không-cờ đi CLI + đối tượng thật không cờ | `dispatch.main()` + `fakevendor` `model_flag: null`. Bẻ `served = None if model=="auto" else model` → `assert 'fake-model' is None` **EXIT 1**. Restore **EXIT 0** | ✅ hết rỗng ruột |
| `claude` 4 nhánh | fake bin: ok `served=claude-opus-5` **EXIT 0**. fail/quota `served=claude-opus-5` **EXIT 1**. `PATH=/usr/bin:/bin` → `reason=not_installed served=claude-opus-5` **EXIT 1**. 0 warning «không nhận cờ» | ✅ 4/4 |
| Revert 2 dòng skip | gỡ `served_model=…` trên skip → `test_vong6_not_installed` `Expected claude-opus-5, got None` **EXIT 1**. Restore **EXIT 0** | ✅ |

## BAO-CAO-VONG10.md · HÀNH VI · khai số

| Họ ghi | Đối chiếu |
|---|---|
| Có mục **HÀNH VI ĐÃ ĐỔI** (served_model trên skip) | **CÓ**. Khớp 2 dòng `dispatcher.py`. **Không nêu** hệ quả `model_flag=null` → lỗ #1 |
| `grep dry-run` 3 dòng · notifier true/false · `grep send` trống | **KHỚP** |
| `152 passed in 7.95s` | số test **KHỚP**. thời gian **LỆCH** (tôi `8.49s`) — không gõ lại số test |
| Revert / claude 4 nhánh / 7 dump / test CLI | **THIẾU dán** (spec bắt). Tôi chạy: revert ĐỎ, claude 4/4, dump 7/7 |
| `python` trần / `python3 -m pytest` / dispatch thiếu prompt | **HẾT** (5 vòng trước có) |

`--send` vẫn `unrecognized arguments` **EXIT 2**. `failover.py` **không** đổi (thiếu `--dry-run` vẫn gửi thật — đúng luật «đừng tự đổi CLI»). Plugin lại gắn `--dry-run`. README · `commands/failover.md` · `CLAUDE.md` khớp nhau.

## Spec 5 + ác ý + ràng buộc

| Kiểm | Kết quả |
|---|---|
| choices từ JSON | bản sao + `zzzfake` → `vendor_names` có `zzzfake`. `--help` gốc vẫn 7. File gốc không đụng |
| `dsh` auto | `--dump-config` `resolved_model=deepseek-v4-pro` (không flash) **EXIT 0** |
| `--doctor` grok/gemini/dsh | cả 3 `doctor: … OK` **EXIT 0** |
| traps stderr | `PATH` cô lập `dsh --result-json`: stderr có `⚠ traps for dsh`, stdout JSON sạch **EXIT 1** |
| vendor lạ / slug lạ / `--send` | **EXIT 2** cả 3 (không im `0`) |
| JSON hỏng / thiếu schema | `JSONDecodeError` / `ValueError schema_version != 3` |
| `--cd` thư mục không có | live `status=error` `os error 2` **EXIT 1** · `served=gpt-5.6-terra` (đã ghim, lệnh chạy) |
| pytest / deps | `152 collected` · `requirements.txt` chỉ stdlib+platformdirs optional · không import mới |
| README/CLAUDE ví dụ | `python3 bin/doctor.py` 7 vendor **EXIT 0**. failover `--dry-run` **EXIT 0**. watcher `--dry-run` `noop` **EXIT 0** |

Không sửa code / không sửa `vendors.json`.
