# ĐỀ BÀI — Vòng 8: thu gọn còn 7 vendor + vá 4 lỗi tài liệu

Repo `~/Developer/polykit`. Đọc `DAP-VONG7.md`, `CLAUDE.md`, `README.md`, `config/vendors.json` trước khi viết dòng nào.

## 📌 QUYẾT ĐỊNH CỦA CHỦ DỰ ÁN — không bàn lại
`vendors.json` đã **gỡ 4 vendor**: `opencode` · `goose` · `zeroclaw` · `jules`. Còn **6 trong JSON** + `openrouter` trong REGISTRY = **7 tên dispatch**.

Lý do (ghi để bạn hiểu, không phải để phản biện):
- `opencode`/`goose`/`zeroclaw` là **LỚP VỎ** gọi OpenRouter — không model riêng, không quota riêng, chỉ khác cú pháp. Đăng ký chúng = đăng ký 3 vỏ cho cùng một nhân. Cần OpenRouter thì gọi thẳng vendor `openrouter`.
- `jules` khác **LOẠI**: làm PR trên repo GitHub từ xa, không nhận prompt → không thuộc dispatch.
- Vé vào sổ = **đã làm được việc thật**, không phải "máy có cài". `dsh` có vé vì đã build ra sản phẩm; 4 cái kia mới ở mức cài-để-xem-UI.

## Việc 1 — 🔴 Sửa 11 test đỏ do việc gỡ
Bản gỡ làm **11 test đỏ / 141 xanh** (trước đó 151 xanh). Nguyên nhân: test vòng 4–6 dùng `opencode` làm **đối tượng thử "vendor chưa biết danh sách model"**, gỡ vendor là gỡ luôn đối tượng.

**Sửa:** chuyển các test đó sang vendor còn lại vẫn "chưa biết model" — `claude` và `gemini` đều có `models` rỗng. Giữ nguyên **ý nghĩa** từng test, đừng xoá test cho hết đỏ.
🔴 Yêu cầu: **0 failed**, và số test **≥151** (đừng giảm bằng cách xoá).
🔴 Phép **revert** vẫn phải hoạt động: hoàn nguyên bản vá vòng 6 (`served_model` ở nhánh error) → phải có test **ĐỎ**.

## Việc 2 — 🔴 Bốn lỗi tài liệu QA vòng 7 tìm ra

### 2a. `python3` KHÔNG có pytest
`CLAUDE.md` đang ghi `python3 -m pytest tests/ -q`. Thực tế `python3` = **3.14.7**, không có pytest:
```
python3 -m pytest tests/ -q
→ /opt/homebrew/opt/python@3.14/bin/python3.14: No module named pytest   EXIT 1
```
⚠️ Vòng trước có người **khai `152 passed` cho đúng lệnh này**. Đừng lặp lại.
**Sửa:** ghi lệnh **chạy được thật**. Kiểm bằng cách chạy.

### 2b. Khối lệnh trong `CLAUDE.md` copy-paste vào zsh là chạy loạn
```
echo "prompt" | python3 bin/dispatch.py <agy|dsh|…|openrouter> [model] --result-json
```
zsh đọc `<a|b|c>` thành **pipeline thật** → `no such file or directory: agy`, `goose panicked`, **EXIT 127**.
**Sửa:** viết sao cho copy-paste **chạy được**, hoặc tách rõ phần ký hiệu khỏi phần lệnh. Tự dán thử vào shell để kiểm.

### 2c. README bảo dùng `--send` — cờ đó KHÔNG tồn tại
```
python3 bin/failover.py --send --pressure 85 → unrecognized arguments: --send   EXIT 2
```
🔴 Nguy hiểm thật: README nói *mặc định `--dry-run`*, nhưng CLI **không** mặc định dry-run → thiếu cờ là **gửi Telegram thật**.
**Sửa:** tài liệu khớp CLI. Nếu hành vi CLI đáng sửa (mặc định nên là dry-run cho an toàn) thì **nêu trong báo cáo**, đừng tự đổi hành vi.

### 2d. Số liệu lạc hậu khắp tài liệu
Vendor: 4 → **7 tên**. Test: 65 → số thật sau khi bạn sửa. Cờ mới `--doctor`, `--allow-unknown-model`, `--no-traps` có tài liệu chưa. `dsh` cần `DEEPSEEK_API_KEY` qua env — người lạ có biết không. Lược đồ `vendors.json` (`headless`, `model_flag`, `models`, `traps`, `zero_quota_cmds`) có được giải thích để người lạ **thêm vendor mới** không.

## 🔴 Ràng buộc CỨNG
1. **KHÔNG thêm lại** 4 vendor đã gỡ. Không bàn lại quyết định đó.
2. 🔴 `pytest` (bằng lệnh chạy được) → **0 failed**, test **≥151**.
3. 🔴 Cả 7 tên (`agy dsh grok codex gemini claude openrouter`) `--dump-config` model mặc định → **exit 0**.
4. Sửa lược đồ thì sửa **cả bên đọc cùng lượt**. Không thêm dependency ngoài stdlib + `requirements.txt`. Giữ P1–P5.
5. Cấm mở `~/Work/`, `~/Claude/Projects/`, `~/Data/`, `~/Downloads/`; cấm `.pdf .jpg .png .xlsx .docx .csv`.

## 🔴 LIVE BEFORE CLAIM — DÁN, ĐỪNG GÕ LẠI
🚨 **BỐN vòng liền bạn khai lệnh không chạy được** (`python` trần exit 127, rồi `python3 -m pytest` exit 1) và khai lệnh dispatch **thiếu prompt**. QA bắt cả bốn lần.
- **Chạy thật rồi DÁN.** Mỗi lệnh trong tài liệu: chạy trước, dán output sau.
- Lệnh dispatch phải có prompt: `printf hi | …`
- Dùng `~/.pyenv/versions/3.11.8/bin/python` cho pytest.

Cần lệnh + output dán nguyên văn + mã thoát cho:
- `pytest` → dòng cuối, ≥151, 0 failed
- 7 tên `--dump-config` → exit 0 (dán vòng lặp + kết quả)
- **Mọi lệnh trong `README.md` và `CLAUDE.md` sau khi sửa** → chạy thật từng cái
- Khối lệnh 2b sau khi sửa → **dán thử vào shell**, chứng minh không exit 127
- `bin/failover.py` với cờ đúng → chứng minh không gửi thật
- Phép **revert** vòng 6 → test ĐỎ

## Trả lời
- `BAO-CAO-VONG8.md`, tiếng Việt, **≤50 dòng**, bảng phẳng. Ghi file ngay khi xong phần đầu.
- Không mở bài, không khen.
