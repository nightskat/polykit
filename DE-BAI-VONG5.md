# ĐỀ BÀI — Vòng 5

Repo `~/Developer/polykit`. Đọc `DAP-VONG4.md`, `CLAUDE.md`, `bin/dispatch.py`, `bin/lib/{dispatcher,dispatch_core,vendor_config}.py`, `config/vendors.json` trước khi viết dòng nào.

## Hai lỗi phải vá

### 1. 🟠 `served_model` BỊA khi lệnh không hề ghim model
`opencode` **không có `model_flag`** → lệnh dựng ra là `opencode run 'hello' < /dev/null`, **không có `--model`**. Nhưng result JSON vẫn điền:
```
served_model = "qwen/qwen3.7-flash (provider openrouter)"
status = ok
```
Đo thật: `model_flag_in_cmd=False` mà `served_model` vẫn có giá trị. **Evidence nói dối về model đã chạy.**

**Sửa:** `served_model` chỉ được điền khi **thật sự biết** model nào đã chạy:
- Lệnh có ghim model (`model_flag` tồn tại và đã đưa vào cmd) → điền slug đã ghim.
- Không ghim được → `served_model = null` + **warning trên stderr và trong `warnings[]`**: vendor này không nhận cờ model, đang chạy mặc định của chính nó, không xác định được slug.
- 🔴 **Không bao giờ suy `served_model` từ `default_model`.** `default_model` là *ta đoán nó dùng gì*; `served_model` là *nó thật sự dùng gì*. Hai khái niệm khác nhau.
- Phụ: `default_model` của `opencode`/`goose`/`zeroclaw`/`jules` đang là **chuỗi mô tả** (`"qwen/qwen3.7-flash (provider openrouter)"`). Tách phần `(provider …)` sang trường riêng, `default_model` chỉ giữ slug thuần.

### 2. 🟡 Vá 2 lỗi vòng 3 mà KHÔNG có test nào khoá hành vi
Grok chứng minh: **revert bản vá về nhánh cũ (`None` → exit 2) thì pytest VẪN 142 xanh.** Tức 142 test **không bảo vệ gì** cho chỗ vừa sửa.

**Sửa — thêm test khoá đúng các hành vi này:**
- Vendor **chưa biết** danh sách model (`claude`, `gemini`, `opencode`…) → `--dump-config` **exit 0** kèm warning. *(khoá lỗi 6/10 vendor chết vòng 3)*
- Vendor **đã biết** danh sách (`dsh`, `agy`, `codex`, `grok`) + slug sai → **exit 2**.
- `models` sai dạng (`dict`, `str`) → **báo lỗi rõ, không im**.
- Lệnh không ghim được model → `served_model is None` **và** có warning. *(khoá lỗi #1 ở trên)*
- **Cả 11 tên** vendor `--dump-config` với model mặc định → exit 0. *(khoá cổng chặn)*

🔴 Tiêu chí: **revert bất kỳ bản vá nào của vòng 3/4/5 thì phải có test ĐỎ.** Test không làm được điều đó thì test vô nghĩa.

## 🔴 Ràng buộc CỨNG
1. Được sửa cả `config/vendors.json` và code — **nhưng sửa lược đồ thì sửa CẢ BÊN ĐỌC cùng lượt**.
2. 🔴 `pytest tests/ -q` phải **0 failed**, và **số test phải TĂNG** (>142) — vì đang thêm test.
3. 🔴 **Cả 11 tên** (`agy dsh grok codex gemini claude opencode goose zeroclaw jules openrouter`) `--dump-config` với model mặc định → **exit 0**.
4. Không thêm dependency ngoài stdlib + `requirements.txt`. Giữ P1–P5 trong `CLAUDE.md`.
5. Cấm mở `~/Work/`, `~/Claude/Projects/`, `~/Data/`, `~/Downloads/`; cấm `.pdf .jpg .png .xlsx .docx .csv`.

## 🔴 LIVE BEFORE CLAIM — DÁN NGUYÊN VĂN, ĐỪNG GÕ LẠI
Mục **"Lệnh đã chạy"** cần lệnh + output **dán nguyên văn** + mã thoát cho:
- `printf hi | $PY bin/dispatch.py opencode --no-traps --result-json --timeout 20` → chứng minh **`served_model: null` + có warning**
- một vendor **có** `model_flag` (vd `dsh`) → chứng minh `served_model` **có giá trị đúng**
- `pytest tests/ -q` → **dán nguyên văn dòng cuối**, số test **phải >142**
- 🔴 **Tự làm phép thử revert**: tạm đổi nhánh `models is None` về `exit 2`, chạy pytest, **chứng minh có test ĐỎ**, rồi hoàn nguyên. Dán output cả hai lần.

⚠️ Vòng trước bạn gõ số từ nhớ và bị bắt: khai `10.211 byte` (thật 10.319), khai `8.02s` (thật 1.00s). Lần này **dán**.
⚠️ Dùng `~/.pyenv/versions/3.11.8/bin/python`. `python` trần **exit 127**.

## Trả lời
- `BAO-CAO-VONG5.md`, tiếng Việt, **≤50 dòng**, bảng phẳng.
- **Ghi file ngay khi vá xong lỗi đầu tiên.**
- Không mở bài, không khen.
