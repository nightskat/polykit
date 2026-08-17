# ĐỀ BÀI — Vòng 4: sửa hồi quy do bản vá vòng 3 đẻ ra

Repo `~/Developer/polykit`. Đọc `DAP-VONG3.md` (QA vòng 3), `CLAUDE.md`, `config/vendors.json`, `bin/dispatch.py`, `bin/lib/vendor_config.py` trước khi viết dòng nào.

## Hai lỗi phải vá

### 1. 🔴 6/10 vendor KHÔNG dispatch được nữa — kể cả với model mặc định của chính nó
Bản vá vòng 3 làm `models` chưa biết ⇒ **chặn MỌI slug**. Hậu quả đo thật:
```
dispatch.py claude --dump-config                  → EXIT 2  ← model mặc định claude-opus-5 HỢP LỆ
dispatch.py claude claude-opus-5 --dump-config    → EXIT 2
dispatch.py gemini gemini-2.5-pro --dump-config   → EXIT 2
dispatch.py opencode --dump-config                → EXIT 2
dispatch.py openrouter some-or-model --dump-config→ EXIT 2   ← openrouter không có trong JSON
```
`goose`, `jules`, `zeroclaw` cũng vậy. Tổng **6/10 vendor chết**.

🔴 **Spec ban đầu nói rõ**: *"chưa biết danh sách model thì **NÓI RÕ là không chặn được**, đừng im"* — **nói rõ ≠ chặn**. Bản vá đọc thành "chặn".

**Sửa cho đúng ý:**
- `models` chưa biết → **CHO PHÉP chạy**, nhưng **in cảnh báo ra stderr**: không xác thực được slug này vì chưa có danh sách.
- `models` đã biết → giữ nguyên hành vi hiện tại: slug ngoài danh sách ⇒ **exit 2** + in danh sách hợp lệ.
- `openrouter` không có trong `vendors.json` nhưng vẫn phải dispatch được (nó sống trong REGISTRY cũ). Xử như trường hợp "chưa biết".
- `--allow-unknown-model` giữ lại để **tắt cả cảnh báo**.

### 2. 🟡 Nhánh đọc `models` sót dạng → lọt im lặng
Code chỉ xử `None` và `list`. Đưa `dict` (lược đồ v2 cũ) thì **nhận bừa, exit 0, không một dòng cảnh báo**. Loader chỉ kiểm `schema_version == 3`, không kiểm **dạng dữ liệu**.
**Sửa:** dạng lạ (`dict`, `str`, số…) ⇒ **báo lỗi rõ ràng nêu tên vendor + dạng gặp phải**, không im. Cân nhắc kiểm dạng ngay trong loader để phát hiện tại chỗ đọc file, không phải lúc dùng.

## 🔴 Ràng buộc CỨNG
1. ✅ Được sửa `config/vendors.json` và code. **NHƯNG sửa lược đồ thì phải sửa CẢ BÊN ĐỌC trong cùng lượt** — bài học đã trả giá 31 test vỡ.
2. 🔴 **`pytest tests/ -q` phải ≥142 passed, 0 failed.** Điều kiện chặn.
3. 🔴 **Cả 10 vendor + `openrouter` phải `--dump-config` được với model mặc định** (exit 0). Đây là tiêu chí mới, đừng để lỗi #1 quay lại dưới dạng khác.
4. Không thêm dependency ngoài stdlib + `requirements.txt` hiện có. Giữ P1–P5 trong `CLAUDE.md`.
5. Cấm mở `~/Work/`, `~/Claude/Projects/`, `~/Data/`, `~/Downloads/`; cấm `.pdf .jpg .png .xlsx .docx .csv`.

## 🔴 LIVE BEFORE CLAIM — và DÁN NGUYÊN VĂN
Mục **"Lệnh đã chạy"** phải có **lệnh + output DÁN NGUYÊN VĂN + mã thoát thật** cho:
- `dump-config` **mọi** vendor với model mặc định: agy · dsh · grok · codex · gemini · claude · opencode · goose · zeroclaw · jules · openrouter → **tất cả exit 0**
- một ca slug sai ở vendor **đã biết** danh sách (vd `dsh totally-fake`) → **exit 2**
- một ca slug lạ ở vendor **chưa biết** danh sách (vd `claude abc`) → **exit 0 + cảnh báo trên stderr**
- một ca `models` sai dạng (dict) → **báo lỗi rõ, không im**
- `pytest tests/ -q` → **dán nguyên văn dòng cuối**

⚠️ **DÁN, đừng gõ lại.** QA vòng 3 bắt được hai con số bạn gõ từ nhớ: khai `10.211 byte` (thật 10.319), khai `pytest in 8.02s` (thật 1.00s). Kết luận đúng nhưng quy trình hở — và lần sau lời bịa lớn sẽ đi qua đúng chỗ hở đó.
⚠️ Dùng `~/.pyenv/versions/3.11.8/bin/python`. `python` trần **không tồn tại** (exit 127).

## Trả lời
- Ghi `BAO-CAO-VONG4.md`, tiếng Việt, **≤50 dòng**, bảng phẳng.
- **Ghi file ngay khi vá xong lỗi đầu tiên.**
- Không mở bài, không khen.
