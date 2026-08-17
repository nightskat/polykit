## (a) HÀNH VI ĐÃ ĐỔI
- Ở nhánh dynamic vendor (JSON), `served_model` cho model không cờ trước đây bị gán bằng `model` trên nhánh `not_installed`. Nay đã chuẩn hoá: mọi nhánh đều báo `served_model=None` + sinh warning "không nhận cờ model" (kể cả `not_installed`). Hành vi này được gom vào hàm `finalize()` chạy trước khi return.

## (b) 2 việc đã vá
| Việc | Mô tả sửa chữa |
|---|---|
| **Việc 1: Vendor giả cố định** | Tạo fixture `fake_vendors` trong `conftest.py` patch `load_vendor_config` để giả lập `fakevendor_no_flag` và `fakevendor_with_flag` cho tất cả các reference trong test. Chuyển 3 test (`test_lenh_khong_ghim_duoc_model...`, `test_vong7_text_duplicate_warning`, `test_dynamic_vendor_from_json`) sang dùng fixture này chạy in-process qua `dispatch.main()`. |
| **Việc 2: Đồng bộ served_model** | Ở `dispatcher.py` (nhánh JSON), dời logic kiểm tra `cmd_has_model` lên trên cùng. Khai báo hàm `finalize()` bọc kết quả trả về của cả 4 nhánh (`ok`, `error`, `quota_capped`, `not_installed`), đảm bảo vendor không cờ luôn trả `served_model=None` và đính kèm chính xác 1 cảnh báo. |

## (c) Lệnh đã chạy
| Kiểm tra | Lệnh | Kết quả / Output thật |
|---|---|---|
| Vendor giả 4 nhánh (không cờ) | `python one_off.py` | `status=ok served=None`<br>`status=error served=None`<br>`status=skipped served=None reason=quota_capped`<br>`status=skipped served=None reason=not_installed`<br>(Tất cả đều có warning: "...không nhận cờ model...") |
| Vendor giả 4 nhánh (có cờ) | `python one_off.py` | `status=ok served=fake-4.6`<br>`status=error served=fake-4.6`<br>`status=skipped served=fake-4.6 reason=quota_capped`<br>`status=skipped served=fake-4.6 reason=not_installed`<br>(Tất cả đều có warnings=[]) |
| Phép revert `test_vong7` (ĐỎ) | Inject 1 dòng stderr warning → `$PY -m pytest tests/test_vong6.py -q` | `FAILED tests/test_vong6.py::test_vong7_text_duplicate_warning - AssertionError: Expected exactly 1 warning, got 2.` **EXIT 1** |
| Phép revert `test_vong7` (XANH) | Gỡ bỏ dòng inject → `$PY -m pytest tests/test_vong6.py -q` | `5 passed in 0.35s` **EXIT 0** |
| File vendors.json | `git diff --quiet config/vendors.json; echo $?` | `0` (Không có thay đổi) |
| Kiểm tra `dry-run` | `grep -n "dry-run" commands/failover.md` | `3:argument-hint: "[...] (luôn chạy --dry-run...)"`<br>`6:Plugin luôn truyền --dry-run...`<br>`8:python3 "...failover.py" --dry-run $ARGUMENTS` |
| Toàn bộ Test suite | `$PY -m pytest tests/ -q` | `152 passed in 9.75s` **EXIT 0** |

## (d) PHÁT HIỆN THÊM — CHƯA VÁ
- Không phát hiện thêm lỗi nằm ngoài scope.
