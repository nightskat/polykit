# ĐỀ BÀI — Vòng 11 (VÒNG CUỐI, phạm vi ĐÓNG BĂNG)

Repo `~/Developer/polykit`. Đọc `DAP-VONG10.md`, `bin/lib/dispatcher.py`, `tests/test_vong5.py`, `tests/test_vong6.py`, `tests/test_vong7*.py` trước khi viết dòng nào.

## 🧊 PHẠM VI ĐÓNG BĂNG — chỉ làm ĐÚNG 2 VIỆC
🔴 **Cấm làm gì ngoài 2 việc dưới.** Không soát tài liệu. Không refactor. Không thêm tính năng. Không sửa vendor nào. Không đổi `vendors.json`.
Thấy lỗi khác → **ghi vào mục "PHÁT HIỆN THÊM — CHƯA VÁ"** ở cuối báo cáo, **để nguyên code**.

Lý do: 10 vòng trước dài vì mỗi vòng lại mở thêm phạm vi. Vòng này phải kết thúc được.

## 🔴 LUẬT BAO TRÙM (đã bị vi phạm 2 lần)
> **KHÔNG sửa hành vi để cho khớp test hay tài liệu.** Xung đột → sửa TEST.
> Muốn đổi hành vi → **viết vào mục "HÀNH VI ĐÃ ĐỔI"** ở ĐẦU báo cáo. Im lặng là lỗi nặng nhất.

## VIỆC 1 — 🔧 Dựng VENDOR GIẢ cố định trong fixture (gốc của 3 vòng lặp lỗi)
**Vấn đề gốc:** ba vòng liền (8, 9, 10) test bị **remap sang vendor THẬT** rồi mất tác dụng:
- vòng 8: remap `opencode` → `claude` (mà `claude` **có** `--model`) ⇒ test khoá hành vi sai
- vòng 10: `test_vong7_text_duplicate_warning` remap sang `claude` + assert `count==0` ⇒ Grok inject thêm 1 dòng warning, test **vẫn xanh**

**Sửa:** dựng **một vendor giả cố định** dùng chung cho mọi test, ví dụ trong `tests/conftest.py`:
- `fakevendor_no_flag` — `model_flag: null`, `models: {}` (vendor **thật sự không nhận cờ model**)
- `fakevendor_with_flag` — có `model_flag`, `models` đầy đủ

🔴 Vendor giả **chỉ tồn tại trong fixture**, **KHÔNG** thêm vào `config/vendors.json`.
Rồi **chuyển các test sau về dùng vendor giả**, giữ nguyên **ý nghĩa** từng test:
- test "vendor không nhận cờ model → `served_model=null` + warning"
- test "cảnh báo hiện đúng 1 lần" (`test_vong7_text_duplicate_warning`)
- test "thêm vendor = sửa JSON" (`test_dynamic_vendor_from_json`)

## VIỆC 2 — 🔴 Nhánh `not_installed` bịa slug
Đo thật (Grok, cùng một vendor giả `model_flag: null`):
```
which=/usr/bin/true  → status=ok        served_model=None      + warning «không nhận cờ»   ← ĐÚNG
which=None           → status=skipped   served_model=fake-4.6  + warnings=[]               ← BỊA
```
Nhánh `skipped/not_installed` gán `served_model=model` **không nhìn `model_flag`**.

**Sửa:** quy tắc `served_model` phải **giống nhau ở CẢ 4 nhánh** (`ok` / `error` / `quota_capped` / `not_installed`):
- vendor **có** `model_flag` → `served_model` = slug đã ghim
- vendor **không** có `model_flag` → `served_model = null` + warning
🔴 Chặn ở **nơi sinh ra giá trị**, đừng thêm `if status == …` cho từng nhánh.

## 🔴 Ràng buộc CỨNG
1. 🧊 **CHỈ 2 việc trên.** Việc khác → ghi báo cáo, để nguyên.
2. 🔴 Không đổi hành vi để test khớp. Không sửa `config/vendors.json` (kiểm: `git diff --quiet config/vendors.json` → 0).
3. 🔴 `$PY -m pytest tests/ -q` → **0 failed**, test **≥152**.
4. 🔴 Cả 7 tên (`agy dsh grok codex gemini claude openrouter`) `--dump-config` → **exit 0**.
5. 🔴 `grep -n "dry-run" commands/failover.md` → **phải còn**.
6. Không thêm dependency ngoài stdlib + `requirements.txt`.
7. Cấm mở `~/Work/`, `~/Claude/Projects/`, `~/Data/`, `~/Downloads/`; cấm `.pdf .jpg .png .xlsx .docx .csv`.

## 🔴 LIVE BEFORE CLAIM — DÁN, ĐỪNG GÕ LẠI
🚨 **NĂM vòng liền** bạn khai lệnh không chạy được. Dùng `~/.pyenv/versions/3.11.8/bin/python`; lệnh dispatch có `printf hi | …`.

Cần lệnh + output **dán nguyên văn** + mã thoát cho:
- Vendor giả `model_flag: null`, **cả 4 nhánh** → `served_model=null` + warning (dán cả 4)
- Vendor giả **có** `model_flag`, cả 4 nhánh → `served_model` = slug đúng
- **Phép revert cho từng test đã chuyển**: bẻ hành vi → test phải **ĐỎ**; hoàn nguyên → xanh. Dán cả hai lần. Đặc biệt: inject thêm một dòng warning → `test_vong7_text_duplicate_warning` phải **ĐỎ** (hiện tại Grok bẻ mà nó vẫn xanh).
- `git diff --quiet config/vendors.json; echo $?` → `0`
- `grep -n "dry-run" commands/failover.md`
- `$PY -m pytest tests/ -q` dòng cuối, ≥152

## Trả lời
- `BAO-CAO-VONG11.md`, tiếng Việt, **≤50 dòng**, bảng phẳng. Ghi file ngay khi xong việc 1.
- Bố cục bắt buộc: **(a) HÀNH VI ĐÃ ĐỔI** (nếu có) · **(b) 2 việc đã vá** · **(c) Lệnh đã chạy** · **(d) PHÁT HIỆN THÊM — CHƯA VÁ**.
- Không mở bài, không khen.
