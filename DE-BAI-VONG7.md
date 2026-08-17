# ĐỀ BÀI — Vòng 7: vá lỗi cuối + soát tài liệu cho người NGOÀI dùng

Repo `~/Developer/polykit`. Đọc `DAP-VONG6.md`, `CLAUDE.md`, `README.md`, `SPEC.md`, `config/vendors.json` trước khi viết dòng nào.

📌 **Bối cảnh mới:** repo này sẽ **mở cho cộng đồng** (nó vốn là Claude Code plugin marketplace). Người đọc `README.md` là **người lạ, không có ngữ cảnh 6 vòng vừa rồi**.

## 1. 🟡 Vá lỗi cuối — warning in TRÙNG ở chế độ text
Đo thật (Grok):
```
printf hi | FAKE_OC_FAIL=1 PATH="/tmp/pk-fakebin:$PATH" $PY bin/dispatch.py opencode \
  --no-traps --allow-unknown-model --timeout 5
stderr:
  [polykit] warning: vendor 'opencode' không nhận cờ model…     ← lần 1, từ run_vendor
  ERROR: opencode failed…
  Warnings:
    - boom: fake fail
    - vendor 'opencode' không nhận cờ model…                     ← lần 2, CLI in lại warnings[]
EXIT 1
```
Chế độ `--result-json` **không trùng**. Chỉ text mode trùng.

**Sửa:** một cảnh báo hiện **đúng một lần** ở mọi chế độ. Tự chọn cách (đừng in ở `run_vendor` nữa, hoặc đừng in lại `warnings[]`) — nhưng **giữ được điều kiện của vòng 6**: chế độ text **vẫn phải thấy** cảnh báo.

## 2. 📖 Soát tài liệu cho người lạ dùng được
`README.md` và `CLAUDE.md` viết từ trước 6 vòng vá, nhiều chỗ **đã lạc hậu**. Việc của bạn: **đối chiếu tài liệu với thực tế bằng cách CHẠY**, không đọc suy.

Tối thiểu phải soát:
- 🔴 Mọi **lệnh ví dụ** trong `README.md`/`CLAUDE.md`: **chạy thử từng cái**. `CLAUDE.md` đang ghi `python bin/dispatch.py …` — trên máy này `python` trần **exit 127**. Ghi lệnh chạy được.
- 🔴 Danh sách vendor: tài liệu ghi 4 (`codex|gemini|claude|grok`), thực tế **11 tên**.
- 🔴 Số test: tài liệu ghi `65 test`, thực tế **151**.
- Trường mới trong `vendors.json` (`headless`, `model_flag`, `models`, `traps`, `zero_quota_cmds`…) — có tài liệu nào giải thích lược đồ chưa? Người thêm vendor mới cần biết điền gì.
- Cờ mới: `--doctor`, `--allow-unknown-model`, `--no-traps` — có trong tài liệu chưa?
- `dsh` là vendor mới, cần **`DEEPSEEK_API_KEY` qua env** — người lạ có biết không?

**Cách ghi:** thêm/sửa tài liệu sao cho **người lạ cài xong chạy được ngay**. Đừng viết lịch sử 6 vòng vá — họ không cần. Viết *hiện tại nó là gì, chạy thế nào, thêm vendor ra sao*.

## 🔴 Ràng buộc CỨNG
1. 🔴 `pytest tests/ -q` **0 failed**, số test **≥151**.
2. 🔴 Cả 11 tên (`agy dsh grok codex gemini claude opencode goose zeroclaw jules openrouter`) `--dump-config` model mặc định → **exit 0**.
3. Chế độ text vẫn phải **thấy** cảnh báo (điều kiện vòng 6, đừng làm mất).
4. Không thêm dependency ngoài stdlib + `requirements.txt`. Giữ P1–P5 trong `CLAUDE.md`.
5. Cấm mở `~/Work/`, `~/Claude/Projects/`, `~/Data/`, `~/Downloads/`; cấm `.pdf .jpg .png .xlsx .docx .csv`.

## 🔴 LIVE BEFORE CLAIM — DÁN, ĐỪNG GÕ LẠI
🚨 **Ba vòng liền bạn khai lệnh `python bin/dispatch.py …` — lệnh đó KHÔNG CHẠY ĐƯỢC (exit 127).** Và khai lệnh dispatch **không có `printf hi |`** nên nó bị chặn ngay, chưa tới nhánh nào. QA đã bắt cả hai. Lần này:
- Dùng `~/.pyenv/versions/3.11.8/bin/python`, **không** `python` trần.
- Lệnh dispatch phải có **prompt** (`printf hi | …`).
- **Dán output nguyên văn**, đừng gõ lại số.

Cần lệnh + output dán nguyên văn + mã thoát cho:
- Chế độ **text** với nhánh lỗi → chứng minh cảnh báo hiện **đúng 1 lần** (dán cả khối stderr)
- Chế độ **`--result-json`** → vẫn 1 lần
- **Mọi lệnh ví dụ trong README/CLAUDE.md sau khi sửa** → chạy thật, dán kết quả
- `pytest tests/ -q` dòng cuối
- Phép **revert** lỗi in trùng → phải có test ĐỎ

## Trả lời
- `BAO-CAO-VONG7.md`, tiếng Việt, **≤50 dòng**, bảng phẳng. Ghi file ngay khi vá xong phần đầu.
- Không mở bài, không khen.
