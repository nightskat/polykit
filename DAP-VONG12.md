KHÔNG TÌM RA CHỖ HỎNG
PY=`~/.pyenv/versions/3.11.8/bin/python` · `$PY -m pytest tests/ -q` → `153 passed in 15.14s` **EXIT 0**. 7/7 `--dump-config` **EXIT 0**. `git diff --quiet config/vendors.json; echo $?` → `0`. `grep -n dry-run commands/failover.md` → dòng 3,6,8. `--help`=`{agy,dsh,grok,codex,gemini,claude,openrouter}` · 4 vendor đã gỡ **không** còn.

## 🔴 Phép revert (tiêu chí chặn)

| Bẻ | Lệnh | Kết quả |
|---|---|---|
| Bỏ `finalize` + `served_model=None if model=="auto" else model` trên nhánh skip | `$PY -m pytest tests/test_vong6.py::test_vong12_dynamic_vendor_not_installed -q --tb=short` | `FAILED` `assert 'fake-model' is None` · `1 failed in 0.05s` **EXIT 1** |
| Cùng bẻ, 7 test cũ vòng 11 | `test_lenh_…` + `test_vong6.py` + `test_dynamic_vendor_from_json` | `1 failed, 7 passed` — **chỉ test mới đỏ** |
| Hoàn nguyên | cùng lệnh test mới | `1 passed in 0.09s` **EXIT 0**. `git diff bin/lib/dispatcher.py` **trống** |

## Lệnh trong BAO-CAO-VONG12 (chạy lại)

| Khai | Thực tế |
|---|---|
| revert `assert 'fake-model' is None` `(1 failed in 0.09s)` | **KHỚP** assertion + EXIT 1 · thời gian **LỆCH** `0.05s` |
| restore `1 passed in 0.06s` | **KHỚP** lần đầu QA (`0.06s`) · sau restore `0.09s` |
| `$PY -m pytest tests/ -q` → `153 passed in 18.09s` | số **KHỚP** · thời gian **LỆCH** `15.14s` |
| `git diff --stat` → `tests/test_vong6.py \| 36 +` | **KHỚP** |
| `python` trần | **HẾT** (lần đầu sau 7 vòng). 3 lệnh đều `~/.pyenv/versions/3.11.8/bin/python` |

## 5 yêu cầu spec + đầu vào ác ý

| # | Lệnh | Exit / output |
|---|---|---|
| 1 choices JSON | `vendor_names(load_vendor_config.__wrapped__(bản_sao + zzzfake))` | `['agy',…,'zzzfake']` · `has_zzz True` |
| 2+3 dsh auto | `$PY bin/dispatch.py dsh --dump-config` | **EXIT 0** `resolved_model=deepseek-v4-pro` (không flash) |
| 4 doctor ×3 | `$PY bin/dispatch.py {dsh,grok,claude} --doctor` | cả 3 **EXIT 0** |
| 5 traps | `grok --result-json` | stdout `trap?=0` · stderr `trap?=1` **EXIT 0** |
| vendor lạ | `nosuchvendor --dump-config` | **EXIT 2** (argparse) |
| slug lạ dsh | `dsh not-a-real-model --dump-config` | **EXIT 2** `error: model … not in vendor 'dsh'` |
| JSON hỏng | `load … '{not json'` | `JSONDecodeError` **EXIT 1** |
| thiếu key `vendors` | schema=3, không `vendors` | load được, `names []` **EXIT 0** |
| không `DEEPSEEK_API_KEY` | `env -u … dsh --dump-config` | **EXIT 0** (dump 0 token, vẫn `deepseek-v4-pro`) |
| `--cd` không tồn tại | `grok --cd /no/such/polykit/dir --dump-config` | **EXIT 0** (dump không kiểm dir) |

## Ràng buộc đóng băng

| Kiểm | Kết quả |
|---|---|
| `git diff --stat` | **chỉ** `tests/test_vong6.py` (+36). Không đụng code / JSON / docs |
| Test HEAD → nay | vong6 `5`→`6` · suite `152`→`153`. Không xoá test |
| `fakevendor` trong JSON | `grep` trống **EXIT 1** |
| `requirements.txt` | không đổi · không import mới |
| Báo cáo có **HÀNH VI ĐÃ ĐỔI** + **PHÁT HIỆN THÊM** | **CÓ** · khai «không đổi / không phát hiện» — khớp diff |

Không sửa code / không sửa `vendors.json`. Inject/revert đã restore.
