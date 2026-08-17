# ĐỀ BÀI — Đập `dispatch.py` v2 (vai QA)

Repo `~/Developer/polykit`. Vừa có người sửa `bin/dispatch.py` để đọc `config/vendors.json` v2.
Spec nó phải theo: `DE-BAI-VONG6.md`. Báo cáo của nó: `BAO-CAO-VONG6.md`.

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
- Ghi `DAP-VONG6.md`, tiếng Việt, **≤70 dòng**, bảng phẳng, có emoji.
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

---
## ⚠️ VÒNG 4 — phạm vi
Hai lỗi bạn tìm vòng 3 **đã được giao vá**: (a) `models` chưa biết ⇒ chặn mọi slug làm **6/10 vendor chết**; (b) nhánh đọc sót dạng `dict` ⇒ **lọt im**.

Kiểm theo thứ tự:
1. 🔴 **`--dump-config` với model mặc định cho CẢ 11 tên** (10 trong JSON + `openrouter`) → phải **exit 0 hết**. Đây là tiêu chí chặn của vòng này.
2. Slug sai ở vendor **đã biết** danh sách → exit 2. Slug lạ ở vendor **chưa biết** → **exit 0 kèm cảnh báo stderr** (không được chặn, cũng không được im).
3. `models` sai dạng (dict/str) → phải **báo lỗi rõ**, không im.
4. `pytest tests/ -q` ≥142 passed 0 failed. Đỏ = chưa xong, báo dòng đầu.
5. Tìm lỗi **MỚI** do bản vá đẻ ra.

🔍 Và kiểm giúp một việc: maker vòng trước **gõ lại số từ nhớ** thay vì dán (khai 10.211 byte / thật 10.319 · khai 8.02s / thật 1.00s). Lượt này soi xem báo cáo có dán nguyên văn không — lệch số dù nhỏ vẫn ghi ra.

---
## ⚠️ VÒNG 5 — phạm vi
Hai lỗi bạn tìm vòng 4 đã giao vá: (a) `served_model` **bịa** khi lệnh không ghim được model; (b) vá mà **0 test khoá hành vi** — revert nhánh vẫn xanh.

Kiểm theo thứ tự:
1. 🔴 `printf hi | $PY bin/dispatch.py opencode --no-traps --result-json` → `served_model` phải **null** + có warning. Vendor **có** `model_flag` (dsh) thì `served_model` phải có giá trị đúng.
2. 🔴 **Tự làm phép revert như bạn đã làm vòng 4**: đổi nhánh `models is None` về `exit 2` → phải có **test ĐỎ**. Nếu vẫn xanh thì test vẫn vô nghĩa, báo ngay dòng đầu.
3. Số test phải **>142** và 0 failed.
4. Cả 11 tên `--dump-config` model mặc định → exit 0.
5. Tìm lỗi **MỚI** do bản vá đẻ ra. Đặc biệt: nới `served_model` có mở đường cho chỗ nào khác bịa không?

---
## ⚠️ VÒNG 6 — phạm vi
Hai lỗi vòng 5 đã giao vá: (a) `served_model=null` **chỉ ở nhánh ok**, nhánh error/quota vẫn bịa slug; (b) warning "không nhận cờ model" **không ra stderr** nên chế độ text mất sạch.

Kiểm theo thứ tự:
1. 🔴 Dựng lại binary giả như bạn đã làm vòng 5 (`FAKE_OC_FAIL`, `FAKE_OC_QUOTA`) → `served_model` phải **null ở CẢ 4 nhánh** (ok/error/quota_capped/not_installed).
2. 🔴 Chạy **chế độ text** (không `--result-json`) → warning phải **có trên stderr**. `--no-traps` cũng không được tắt nó.
3. Test **>147**, 0 failed. Test phải đi qua **đường CLI thật**, không chỉ gọi hàm với `model="auto"` — đó là điểm hở bạn đã chỉ ra.
4. Phép **revert** từng lỗi → phải có test ĐỎ.
5. Tìm lỗi **MỚI**. Đặc biệt: chặn `served_model` ở nơi sinh giá trị có làm mất `served_model` ĐÚNG của vendor có `model_flag` không?
