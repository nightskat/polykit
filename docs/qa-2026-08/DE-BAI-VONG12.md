# ĐỀ BÀI — Vòng 12 (VÒNG CUỐI THẬT, phạm vi ĐÓNG BĂNG: ĐÚNG 1 VIỆC)

Repo `~/Developer/polykit`. Đọc `DAP-VONG11.md`, `bin/lib/dispatcher.py`, `tests/conftest.py`, `tests/test_vong5.py`, `tests/test_vong6.py` trước khi viết dòng nào.

## 🧊 CHỈ LÀM ĐÚNG MỘT VIỆC
🔴 Không refactor. Không sửa tài liệu. Không sửa `config/vendors.json`. Không đổi hành vi. Không thêm tính năng.
Thấy lỗi khác → ghi mục **"PHÁT HIỆN THÊM — CHƯA VÁ"** ở cuối báo cáo, **để nguyên code**.

## VIỆC DUY NHẤT — 🔴 Thêm test khoá nhánh `not_installed`
Hành vi hiện tại **đã ĐÚNG** (vòng 11 vá rồi, Grok xác nhận):
```
vendor giả KHÔNG có model_flag → served_model=None + warning  ở CẢ 4 nhánh
vendor giả CÓ    model_flag    → served_model=<slug>, warnings=[]  ở CẢ 4 nhánh
```
🔴 **Nhưng KHÔNG có test nào khoá nhánh `not_installed`.** Grok chứng minh:
```
Tạm trả DispatchResult(... served_model = None if model=="auto" else model) — KHÔNG qua finalize
$PY -m pytest tests/test_vong5.py::test_lenh_... tests/test_vong6.py \
              tests/test_dispatch_v2.py::TestVong2::test_dynamic_vendor_from_json -q
→ 7 passed in 0.86s   EXIT 0     ← bẻ hành vi mà VẪN XANH
```
Nghĩa là vòng sau ai sửa gì đó thì nhánh này **lặng lẽ hỏng lại**.

**Việc của bạn:** thêm test (dùng **vendor giả trong `tests/conftest.py`** đã có, đừng dựng mới, đừng thêm vào `vendors.json`) khoá đúng hành vi:
- vendor **không** `model_flag`, nhánh `not_installed` → `served_model is None` **và** có warning
- vendor **có** `model_flag`, nhánh `not_installed` → `served_model` = slug đã ghim
- Đi qua **đường thật** (`run_vendor` với `which=None`), không mock kết quả cuối.

🔴 **Điều kiện nghiệm thu — phép revert:**
Bẻ nhánh skip đúng như Grok đã bẻ (`served_model = None if model=="auto" else model`, bỏ qua `finalize`) → **test mới phải ĐỎ**. Hoàn nguyên → xanh. **Dán output cả hai lần.**
Nếu bẻ mà test vẫn xanh thì test vô nghĩa — làm lại, đừng nộp.

## 🔴 Ràng buộc CỨNG
1. 🧊 **CHỈ 1 việc trên.**
2. 🔴 **Không đổi hành vi** — hành vi đang đúng, chỉ thiếu test. Muốn đổi → viết mục "HÀNH VI ĐÃ ĐỔI", để nguyên code.
3. 🔴 `$PY -m pytest tests/ -q` → **0 failed**, test **>152** (đang thêm test, số phải tăng).
4. 🔴 `git diff --quiet config/vendors.json; echo $?` → `0`.
5. 🔴 `grep -n "dry-run" commands/failover.md` → phải còn.
6. 🔴 Cả 7 tên (`agy dsh grok codex gemini claude openrouter`) `--dump-config` → exit 0.
7. Không thêm dependency. Cấm mở `~/Work/`, `~/Claude/Projects/`, `~/Data/`, `~/Downloads/`; cấm `.pdf .jpg .png .xlsx .docx .csv`.

## 🚨 LỆNH TRONG BÁO CÁO — SẼ BỊ MÁY KIỂM
**SÁU vòng liền** bạn khai lệnh `python …` — `python` trần **không tồn tại trên máy này** (`pyenv: python: command not found`, EXIT 127).
🔴 Lượt này có **cổng tự động grep báo cáo**: tìm thấy `python ` trần (không phải `python3` / không phải đường dẫn đầy đủ) → **báo cáo BỊ TỪ CHỐI**, coi như chưa xong.
👉 Dùng `~/.pyenv/versions/3.11.8/bin/python`. **DÁN output, đừng gõ lại.**

Cần lệnh + output dán nguyên văn + mã thoát cho:
- Test mới: nhánh `not_installed` cả hai loại vendor giả
- **Phép revert**: bẻ → ĐỎ (dán), hoàn nguyên → xanh (dán)
- `$PY -m pytest tests/ -q` dòng cuối, **>152**
- `git diff --quiet config/vendors.json; echo $?` → `0`
- `git diff --stat` → chứng minh **chỉ sửa file test**

## Trả lời
- `BAO-CAO-VONG12.md`, tiếng Việt, **≤30 dòng**.
- Bố cục: **(a) HÀNH VI ĐÃ ĐỔI** (nếu có) · **(b) test đã thêm** · **(c) Lệnh đã chạy** · **(d) PHÁT HIỆN THÊM — CHƯA VÁ**.
- Không mở bài, không khen.
