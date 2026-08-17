# ĐỀ BÀI — Vòng 3: sửa LƯỢC ĐỒ và CODE cùng lúc

Repo `~/Developer/polykit`. Đọc `DAP-VONG2.md` (QA vòng 2), `CLAUDE.md`, `SPEC.md`, `config/vendors.json`, `bin/dispatch.py`, `bin/lib/vendor_config.py` trước khi viết dòng nào.

## Ba lỗi phải vá — gốc đều ở LƯỢC ĐỒ, không ở code

### 1. 🔴 `zero_quota_cmds` mang BA nghĩa khác nhau
```
agy    → ["/model", "/usage"]                  ← lệnh NỘI BỘ, phải gọi: agy -p "/model"
dsh    → ["--dump-config"]                     ← CỜ, phải ghép: dsh --profile headless --dump-config
codex  → ["codex debug models", "codex doctor"] ← lệnh SHELL đủ
```
Hậu quả đo thật (Grok):
- `dispatch.py dsh --doctor` → **exit 1 dù dsh SỐNG** (`error: --profile <name> is required`). Doctor khoẻ báo thành bệnh.
- `dispatch.py codex --doctor` → stdout **304.814 byte** (`codex debug models` đổ cả system prompt).
- `dispatch.py agy --doctor` → in model **2 lần** (verify_cmd rồi zq trùng nhau).
- Bản vá vòng 2 chỉ bắt `vcmd == "dsh --dump-config"` → **code chết**, JSON đã là bản có `--profile`.

**Sửa:** chọn **MỘT nghĩa duy nhất** cho trường này và làm cho mọi vendor đi cùng một đường. Đề xuất: **lệnh shell đầy đủ, chạy nguyên văn**. Nếu bạn thấy cách khác tốt hơn thì làm, nhưng phải **một nghĩa**.
Bỏ `codex debug models` khỏi zero_quota (304KB), giữ `codex doctor`.
`--doctor` phải **exit 0 khi vendor sống**, khác 0 khi thật sự lỗi, và **không in trùng**.

### 2. 🟠 Vendor mất binary → bịa `served_model`
`env PATH=/usr/bin:/bin dispatch.py opencode --result-json` → `status=error exit_code=127 command not found` nhưng vẫn điền `served_model=qwen/...`. Theo P1 trong `CLAUDE.md` phải là `not_installed`/`skipped`, và **không được bịa** model chưa từng chạy.

### 3. 🟠 Chặn model bịa chỉ khi `models` là dict
`models` khi thì dict `{họ: [slug]}`, khi thì chuỗi `"CHUA_KIEM"`. Nên `dispatch.py claude totally-fake-model --dump-config` → **exit 0**, nhận bừa. `gemini`, `openrouter` cũng vậy.
**Sửa:** `models` một dạng duy nhất. Dạng "chưa biết" phải phân biệt được với "biết và rỗng", và khi chưa biết thì **nói rõ là không chặn được**, đừng im.

## 🔴 Ràng buộc CỨNG
1. ✅ **ĐƯỢC PHÉP sửa `config/vendors.json`** (khác vòng trước) — vì lỗi gốc nằm trong dữ liệu. **NHƯNG:**
2. 🔴 **Sửa lược đồ thì phải sửa CẢ BÊN ĐỌC trong cùng một lượt.** JSON và code là **hợp đồng hai phía**; sửa một phía là phá hợp đồng. Người trước đã thử đổi JSON riêng lẻ → **31 test vỡ ngay**.
3. 🔴 **`pytest tests/ -q` phải ra ĐÚNG 142 passed trở lên, 0 failed.** Đây là điều kiện chặn, không phải mục tiêu phấn đấu. Chưa xanh thì chưa xong.
4. Không thêm dependency ngoài stdlib + `requirements.txt` hiện có.
5. Giữ nguyên P1–P5 trong `CLAUDE.md`. Đặc biệt P1: vendor thiếu **không gây lỗi, không skip im lặng**.
6. Cấm mở `~/Work/`, `~/Claude/Projects/`, `~/Data/`, `~/Downloads/`; cấm `.pdf .jpg .png .xlsx .docx .csv`.
7. Bump `schema_version` nếu đổi lược đồ, và ghi luật mới vào `_luat`.

## 🔴 LIVE BEFORE CLAIM
Mục **"Lệnh đã chạy"** phải có **nguyên văn lệnh + output thật + mã thoát thật** cho tối thiểu:
- `dispatch.py dsh --doctor` → chứng minh **exit 0** (dsh đang sống)
- `dispatch.py codex --doctor` → chứng minh stdout **không còn ~300KB**
- `dispatch.py agy --doctor` → chứng minh **không in trùng**
- `dispatch.py claude totally-fake-model --dump-config` → chứng minh **exit 2**
- `env PATH=/usr/bin:/bin dispatch.py opencode --result-json` → chứng minh **không bịa `served_model`**
- `pytest tests/ -q` → **nguyên văn dòng cuối**
- `python3 -c 'import json;json.load(open("config/vendors.json"))'` → hợp lệ

⚠️ Dùng `~/.pyenv/versions/3.11.8/bin/python`. **`python` trần không tồn tại trên máy này (exit 127)** — vòng 1 có người khai lệnh `python …` và bị bắt vì thế.
⚠️ QA sẽ chạy lại đúng những lệnh bạn khai.

## Trả lời
- Ghi `BAO-CAO-VONG3.md`, tiếng Việt, **≤50 dòng**, bảng phẳng.
- **Ghi file ngay khi vá xong lỗi đầu tiên**, cập nhật dần.
- Không mở bài, không khen, không tổng kết lại đề bài.
