# ĐỀ BÀI — Vòng 6

Repo `~/Developer/polykit`. Đọc `DAP-VONG5.md`, `CLAUDE.md`, `bin/dispatch.py`, `bin/lib/{dispatcher,dispatch_core}.py` trước khi viết dòng nào.

## Hai lỗi phải vá

### 1. 🟠 `served_model=null` chỉ áp cho nhánh `status==ok`
Vòng 5 vá đúng nhánh thành công, **bỏ sót nhánh thất bại**. Đo thật (Grok dựng binary giả):
```
FAKE_OC_FAIL=1  → status=error   served_model=qwen/qwen3.7-flash   ← BỊA
FAKE_OC_QUOTA=1 → status=skipped served_model=qwen/qwen3.7-flash   ← BỊA
status=ok       → served_model=null + warning                      ← đúng
PATH cắt        → not_installed  served_model=null                 ← đúng
```
Gốc: CLI resolve `auto` → `default_model` **rồi mới** gọi `run_vendor(slug)`; `_classify_completed` lấy slug đó điền vào `served_model` bất kể lệnh có ghim model hay không.

**Sửa:** quy tắc `served_model` áp **cho MỌI nhánh** (`ok`, `error`, `skipped`, `quota_capped`):
- Lệnh **có** ghim model → điền slug đã ghim.
- Lệnh **không** ghim được (vendor thiếu `model_flag`) → `served_model = null` + warning, **ở mọi nhánh**.
- 🔴 Đừng vá bằng `if status == …`. Hãy làm sao **không có đường nào** điền `served_model` từ `default_model`. Chặn ở nơi sinh ra giá trị, không chặn ở từng cửa ra.

### 2. 🟡 Warning "không nhận cờ model" chỉ vào `warnings[]`, không ra stderr
Spec vòng 5 ghi **"stderr VÀ `warnings[]`"**. Vá chỉ nhét JSON ⇒ chạy chế độ text (không `--result-json`) thì **mất sạch cảnh báo**.
Đo: stderr chỉ có dòng `cannot validate`, không có dòng nào nói vendor không nhận cờ model.

**Sửa:** warning ra **cả hai**: stderr (mọi chế độ) và `warnings[]` (khi có JSON). `--no-traps` không được tắt cảnh báo này — nó là cảnh báo về **tính đúng của evidence**, không phải mẹo dùng CLI.

## 🔴 Test — điểm hở vòng 5
Test mới của vòng 5 gọi thẳng `model="auto"` nên **không đi qua đường CLI thật**, do đó không khoá được lỗi #1.
**Yêu cầu:** test phải đi qua **đúng đường CLI dùng thật** (resolve auto → run_vendor → classify), và phủ **cả 4 nhánh** `ok / error / quota_capped / not_installed`.

🔴 **Tự làm phép revert cho từng lỗi**: hoàn nguyên bản vá → phải có test ĐỎ → rồi trả lại. Dán output cả hai lần. Vòng 5 đã làm được (`2 failed, 145 passed`), vòng này làm tiếp cho 2 lỗi mới.

## 🔴 Ràng buộc CỨNG
1. Sửa lược đồ thì sửa **cả bên đọc cùng lượt**.
2. 🔴 `pytest tests/ -q` **0 failed**, số test **>147**.
3. 🔴 Cả 11 tên (`agy dsh grok codex gemini claude opencode goose zeroclaw jules openrouter`) `--dump-config` model mặc định → **exit 0**.
4. Không thêm dependency ngoài stdlib + `requirements.txt`. Giữ P1–P5 trong `CLAUDE.md`.
5. Cấm mở `~/Work/`, `~/Claude/Projects/`, `~/Data/`, `~/Downloads/`; cấm `.pdf .jpg .png .xlsx .docx .csv`.

## 🔴 LIVE BEFORE CLAIM — DÁN, ĐỪNG GÕ LẠI
Cần lệnh + output **dán nguyên văn** + mã thoát cho:
- Nhánh **lỗi**: dựng binary giả rồi chạy → chứng minh `served_model=null`
- Nhánh **quota**: tương tự
- Nhánh **ok**: `served_model=null` + warning
- Vendor **có** `model_flag` (dsh): `served_model` có giá trị đúng
- **Chế độ text** (không `--result-json`): chứng minh warning **có trên stderr**
- `pytest tests/ -q` dòng cuối, số test **>147**
- Phép **revert** từng lỗi: trước (đỏ) và sau (xanh)

⚠️ `~/.pyenv/versions/3.11.8/bin/python`. `python` trần exit 127.
⚠️ Đã bị bắt gõ số từ nhớ 2 lần. **Dán.**

## Trả lời
- `BAO-CAO-VONG6.md`, tiếng Việt, **≤50 dòng**, bảng phẳng. Ghi file ngay khi vá xong lỗi đầu.
- Không mở bài, không khen.
