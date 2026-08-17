## (a) HÀNH VI ĐÃ ĐỔI
- Không thay đổi hành vi code gốc, chỉ thêm test.

## (b) test đã thêm
- Thêm `test_vong12_dynamic_vendor_not_installed` vào `tests/test_vong6.py`.
- Khoá đường đi nhánh `not_installed` với `fakevendor_no_flag` (ra `served_model=None` + có warning) và `fakevendor_with_flag` (ra `served_model=fake-model` + không có warning).

## (c) Lệnh đã chạy
- **Bẻ lỗi (sửa nhánh skip như Grok):**
  `~/.pyenv/versions/3.11.8/bin/python -m pytest tests/test_vong6.py::test_vong12_dynamic_vendor_not_installed -q`
  -> `FAILED tests/test_vong6.py::test_vong12_dynamic_vendor_not_installed - AssertionError: assert 'fake-model' is None` (1 failed in 0.09s)
- **Hoàn nguyên:**
  `~/.pyenv/versions/3.11.8/bin/python -m pytest tests/test_vong6.py::test_vong12_dynamic_vendor_not_installed -q`
  -> `1 passed in 0.06s`
- **Chạy toàn bộ test:**
  `~/.pyenv/versions/3.11.8/bin/python -m pytest tests/ -q`
  -> `153 passed in 18.09s`
- **Kiểm tra JSON và diff:**
  `git diff --quiet config/vendors.json; echo $?` -> `0`
  `git diff --stat` -> `tests/test_vong6.py | 36 ++++++++++++++++++++++++++++++++++++`

## (d) PHÁT HIỆN THÊM — CHƯA VÁ
- Không phát hiện thêm lỗi nào nằm ngoài phạm vi yêu cầu.
