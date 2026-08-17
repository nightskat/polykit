# ĐỀ BÀI — Đập `dispatch.py` v2 (vai QA)

Repo `~/Developer/polykit`. Vừa có người sửa `bin/dispatch.py` để đọc `config/vendors.json` v2.
Spec nó phải theo: `DE-BAI-VONG3.md`. Báo cáo của nó: `BAO-CAO-VONG3.md`.

## Giả định mặc định
🔴 **Báo cáo có chỗ khai khống.** Phiên 17/08 đã bắt hai vụ: một model ghi `grep tuan → trống` (thực tế 3 dòng); một model báo `52 test passed` (thực tế bộ test không thu thập nổi). **Đừng tin dòng nào chưa tự chạy.**

## Việc

### 1. Chạy lại mục "Lệnh đã chạy"
Từng lệnh một. Ghi `KHỚP` / `LỆCH (thực tế là gì)` / `KHÔNG CHẠY ĐƯỢC`.

### 2. Kiểm 5 yêu cầu của spec, mỗi cái bằng lệnh thật
| # | Kiểm gì | Gợi ý |
|---|---|---|
| 1 | `choices` sinh từ JSON, không hard-code | Thêm vendor giả vào **bản sao** JSON rồi trỏ vào; hoặc đọc code. **Không sửa file gốc** |
| 2 | `dsh` dispatch được | Chạy thật, dùng `--dump-config` (0 token) chứng minh ghim đúng `deepseek-v4-pro` |
| 3 | `auto` → `default_model`, và `dsh` auto **không được** ra `flash` | flash trả rỗng trên task nhiều bước — ra flash là lỗi NẶNG |
| 4 | `--doctor <vendor>` | Chạy cho ít nhất 3 vendor |
| 5 | `traps` in ra **stderr**, không lẫn stdout | `cmd 2>/dev/null` xem stdout còn sạch không |

### 3. Đầu vào ác ý
Vendor không tồn tại · model không có trong `models` của vendor đó · JSON hỏng · thiếu key · `DEEPSEEK_API_KEY` không có · thư mục làm việc không tồn tại.
Mỗi ca: **mã thoát thật**. Chết im lặng mà `exit 0` là lỗi nặng nhất.

### 4. Ràng buộc có bị phá không
- `config/vendors.json` có bị sửa không? → `git diff config/vendors.json` phải TRỐNG.
- Có thêm dependency không? → so `requirements.txt` + import trong code.
- Test cũ còn xanh không?

## Cấm
- Cấm sửa code, cấm sửa `vendors.json`. Bạn đập, không vá.
- Cấm nhận xét chung chung — mỗi phát hiện = **lệnh + output thật + mã thoát thật**.
- Cấm mở `~/Work/`, `~/Claude/Projects/`, `~/Data/`, `~/Downloads/`; cấm `.pdf .jpg .png .xlsx .docx .csv`.

## Định dạng
- Ghi `DAP-VONG3.md`, tiếng Việt, **≤70 dòng**, bảng phẳng, có emoji.
- Dòng đầu: `HỎNG N CHỖ` / `KHÔNG TÌM RA CHỖ HỎNG`.
- Xếp theo **mức thiệt hại**, nặng nhất lên đầu.
- ⚠️ **Ghi file NGAY khi có phát hiện đầu tiên.** Bạn có giới hạn số lượt — dồn đến cuối là mất sạch.

---
## ⚠️ ĐÂY LÀ VÒNG 2 — đừng báo lại lỗi cũ
Vòng 1 bạn tìm 4 lỗi, **cả 4 đã được vá**: `--doctor` báo OK giả · `openrouter` mất khỏi CLI · vendor mới ra `unknown_vendor` · model bịa vẫn nhận.
Việc vòng này: **(a)** xác nhận 4 lỗi đó đã hết THẬT bằng chính lệnh bạn đã dùng vòng 1, **(b)** tìm lỗi **MỚI** do bản vá đẻ ra.

🔴 Kiểm bắt buộc: `git diff --quiet config/vendors.json; echo $?` phải in `0`. Khác 0 = maker phá ràng buộc cứng, báo ngay ở dòng đầu.

---
## ⚠️ VÒNG 3 — phạm vi
Vòng 2 bạn tìm 3 lỗi mới, **cả 3 đã được giao vá**: `zero_quota_cmds` ba nghĩa (doctor báo bệnh cho vendor khoẻ, codex đổ 304KB, agy in trùng) · vendor mất binary bịa `served_model` · chặn model bịa chỉ khi `models` là dict.

Việc vòng này:
1. **Xác nhận 3 lỗi đó đã hết THẬT** bằng chính lệnh bạn dùng vòng 2.
2. 🔴 **Lượt này maker ĐƯỢC PHÉP sửa `config/vendors.json`.** Nên đừng kiểm "JSON có bị đụng không" — thay vào đó kiểm: **JSON đổi lược đồ thì CODE ĐỌC có đổi theo chưa?** Người trước đổi JSON riêng lẻ làm **31 test vỡ**.
3. Kiểm `pytest tests/ -q` phải **≥142 passed, 0 failed**. Chưa xanh = chưa xong, báo ngay dòng đầu.
4. Tìm lỗi **MỚI** do bản vá đẻ ra — đặc biệt chỗ lược đồ đổi mà một bên đọc nào đó bị bỏ sót.
