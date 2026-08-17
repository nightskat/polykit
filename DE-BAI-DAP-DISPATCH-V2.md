# ĐỀ BÀI — Đập `dispatch.py` v2 (vai QA)

Repo `~/Developer/polykit`. Vừa có người sửa `bin/dispatch.py` để đọc `config/vendors.json` v2.
Spec nó phải theo: `DE-BAI-DISPATCH-V2.md`. Báo cáo của nó: `BAO-CAO-DISPATCH-V2.md`.

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
- Ghi `DAP-DISPATCH-V2.md`, tiếng Việt, **≤70 dòng**, bảng phẳng, có emoji.
- Dòng đầu: `HỎNG N CHỖ` / `KHÔNG TÌM RA CHỖ HỎNG`.
- Xếp theo **mức thiệt hại**, nặng nhất lên đầu.
- ⚠️ **Ghi file NGAY khi có phát hiện đầu tiên.** Bạn có giới hạn số lượt — dồn đến cuối là mất sạch.
