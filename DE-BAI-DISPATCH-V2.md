# ĐỀ BÀI — Cho `dispatch.py` đọc được `vendors.json` v2

Repo: `~/Developer/polykit`. Đọc `README.md`, `SPEC.md`, `CLAUDE.md`, `bin/dispatch.py` và `config/vendors.json` **trước khi viết dòng nào**.

## Hiện trạng
`config/vendors.json` vừa nâng lên **schema v2**: 10 vendor, mỗi vendor có `headless`, `model_flag`, `default_model`, `models`, `traps`, `verify_cmd`, `zero_quota_cmds`…
`bin/dispatch.py` thì **chưa biết gì về nó**: dòng 15 hard-code `choices=["gemini","codex","claude","grok","agy","openrouter"]` — thiếu `dsh`, thiếu `opencode`/`goose`/`zeroclaw`/`jules`, và không đọc `traps` hay `default_model`.

## Việc

### 1. Đọc vendor từ file, bỏ hard-code
`choices` phải sinh từ `config/vendors.json`. Thêm vendor mới = sửa JSON, **không sửa code**.

### 2. Thêm `dsh`
Đặc thù: **không có cờ `--model`**. Muốn ghim model phải sinh file patch YAML tạm rồi truyền `--patch`:
```yaml
- id: agent-default-model
  config: {provider: deepseek-official, model: deepseek-v4-pro}
```
Key lấy từ Keychain rồi bơm qua env `DEEPSEEK_API_KEY`.
🔴 `deepseek-v4-flash` **trả về rỗng** trên task nhiều bước (tái hiện 2 lần). Khi gọi `dsh` mà người dùng để `auto` → **mặc định phải là `deepseek-v4-pro`**, không phải flash.

### 3. `model auto` = lấy `default_model` trong JSON
Hiện `auto` là chuỗi truyền thẳng. Sửa: `auto` → tra `default_model` của vendor đó rồi ghim tường minh.
Lý do: **mặc định của mọi CLI đều là tầng rẻ nhất của nó** — không ghim thì luôn nhận tầng đáy mà không ai báo.

### 4. `--doctor <vendor>`
Chạy `verify_cmd`, in vendor còn sống + model đang chạy. Ưu tiên lệnh trong `zero_quota_cmds`.

### 5. In cảnh báo bẫy
Trước khi chạy, in `traps` của vendor đó ra **stderr** (không lẫn stdout). Có cờ `--no-traps` để tắt.

## Ràng buộc CỨNG
1. 🔴 **KHÔNG sửa `config/vendors.json`.** Nó là dữ liệu đã kiểm chứng, bạn chỉ đọc.
2. 🔴 **Không thêm dependency** ngoài thư viện chuẩn Python + thứ `requirements.txt` đã có.
3. Test hiện có phải xanh nguyên. Thêm test cho phần mới.
4. **Đọc file cùng thư mục trước khi viết** — theo đúng lối import/cấu trúc sẵn có, đừng viết theo sách vở rồi lệch với hàng xóm.
5. Cấm mở `~/Work/`, `~/Claude/Projects/`, `~/Data/`, `~/Downloads/`; cấm mở `.pdf .jpg .png .xlsx .docx .csv`.

## 🔴 LIVE BEFORE CLAIM — điều kiện nghiệm thu
Báo cáo **không được** ghi "đã test" chung chung. Bắt buộc:
- Mục **"Lệnh đã chạy"** liệt kê **nguyên văn** mọi lệnh, kèm **output thật** và **mã thoát thật**.
- Ít nhất **một lượt dispatch thật** qua `dsh` chứng minh nó ghim đúng `deepseek-v4-pro` (dùng `--dump-config`, tốn 0 token).
- Ít nhất **một lượt `--doctor`** thật.
- ⚠️ Phiên 17/08 đã bắt được hai vụ khai khống: một model ghi `grep tuan → trống` trong khi lệnh ra 3 dòng; một model báo `52 test passed` trong khi bộ test **không chạy nổi**. Cả hai bị vạch trần bằng cách **chạy lại đúng lệnh đã khai**. Sẽ có người làm đúng như vậy với bạn.

## Trả lời
- Viết code vào repo. Chạy test đến khi xanh.
- Ghi `BAO-CAO-DISPATCH-V2.md`, tiếng Việt, **≤50 dòng**, bảng phẳng.
- **Ghi file ngay khi xong phần đầu tiên**, cập nhật dần — hết lượt mà chưa ghi là mất trắng.
- Không mở bài, không khen.
