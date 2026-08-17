# ĐỀ BÀI — Vòng 9

Repo `~/Developer/polykit`. Đọc `DAP-VONG8.md`, `CLAUDE.md`, `README.md`, `commands/*.md`, `bin/lib/dispatch_core.py` trước khi viết dòng nào.

## 🔴 Nguyên tắc bao trùm vòng này
> **KHÔNG BAO GIỜ sửa hành vi để cho khớp bài kiểm tra.**
> Nếu test và hành vi đúng xung đột → **sửa TEST**, giữ hành vi. Nếu không chắc cái nào đúng → **ghi vào báo cáo và để nguyên**, đừng đoán.

Vòng 8 đã vi phạm điều này: được bảo *"chuyển test từ opencode sang claude"*, maker chuyển test **rồi bẻ hành vi `claude`** cho test xanh. Xem lỗi 1.

## Lỗi 1 — 🔴 `claude` bị bẻ hành vi: giấu model đã ghim
Sự thật đo được (Grok, binary giả):
```
cmd thật:  claude --model claude-opus-5 --effort low … -p hi     ← CÓ ghim model
JSON trả:  model=claude-opus-5  served_model=null
           warnings=["vendor 'claude' không nhận cờ model…"]     ← NÓI DỐI
```
`build_claude_cmd()` chứng minh cờ `--model` **có** trong lệnh:
```
PYTHONPATH=bin $PY -c "from lib.dispatch_core import build_claude_cmd; print(build_claude_cmd('claude-opus-5','hi'))"
→ ['claude', '--model', 'claude-opus-5', …]
```
**Sửa:** `claude` **có** ghim model ⇒ `served_model` phải là **`claude-opus-5`**, và **không** được có warning "không nhận cờ model". Áp cho **cả 4 nhánh** (ok/error/quota/not_installed).
🔴 Rồi **sửa test vòng 6 cho khớp hành vi ĐÚNG** — hiện chúng đang khoá hành vi sai.
🔴 Test "vendor không nhận cờ model" cần một đối tượng **thật sự** không nhận cờ. `grok` **không có `model_flag`** trong JSON → dùng `grok`, hoặc dựng vendor giả trong fixture. **Đừng bẻ vendor thật.**

## Lỗi 2 — 🔴 `--send` sót + tài liệu nói NGƯỢC + rủi ro gửi thật
- `commands/failover.md` vẫn bảo *mặc định dry-run, thêm `--send` để gửi thật*. CLI **không có `--send`** → `EXIT 2`.
- README nói plugin *"mặc định GỬI THẬT"*, nhưng plugin **luôn** gắn `--dry-run`. **Nói ngược nhau.**
- 🔴 Rủi ro thật, Grok chứng minh bằng notifier giả:
```
POLYKIT_NOTIFIER=/tmp/fake.sh python3 bin/failover.py --pressure 85  → notified: true  (GỌI THẬT)
… --pressure 85 --dry-run                                            → notified: false (không gọi)
```
**Sửa:** tài liệu (`README.md`, `commands/failover.md`, `CLAUDE.md`) khớp **đúng** hành vi CLI, và **thống nhất với nhau**.
💡 Nếu bạn cho rằng CLI nên **mặc định `--dry-run`** cho an toàn (thiếu cờ là gửi thật, dễ gây tai nạn) → **nêu trong báo cáo**, kèm lý do. **Đừng tự đổi hành vi** — đó là quyết định của chủ dự án.

## Lỗi 3 — 🟡 `commands/dispatch.md` thiếu vendor
Còn 5 tên (`codex|gemini|claude|grok|openrouter`), thiếu **`agy`** và **`dsh`**. `--help` có đủ 7.
**Sửa:** soát **mọi** file trong `commands/` cho khớp 7 tên.

## Lỗi 4 — 🟡 Test mất khả năng khoá "thêm vendor = sửa JSON"
`test_dynamic_vendor_from_json` đổi sang `claude` (vendor có **nhánh cứng** `build_claude_cmd`), chỉ còn assert `cmd[0]=="claude"` — bỏ mất assert `opencode run` + `< /dev/null`.
**Sửa:** test đó phải dùng **vendor CHỈ TỒN TẠI TRONG JSON** (dựng vendor giả trong fixture, đừng thêm lại vendor đã gỡ) và assert lệnh được dựng **từ trường `headless`**, chứng minh thêm vendor **không cần sửa code**.
Phụ: `CLAUDE.md` M1b còn ghi `detect 4 vendor` → sửa cho khớp.

## 🔴 Ràng buộc CỨNG
1. **KHÔNG thêm lại** `opencode`/`goose`/`zeroclaw`/`jules`.
2. 🔴 **KHÔNG sửa hành vi để test xanh.** Xung đột thì sửa test.
3. 🔴 `$PY -m pytest tests/ -q` → **0 failed**, test **≥152**.
4. 🔴 Cả 7 tên (`agy dsh grok codex gemini claude openrouter`) `--dump-config` model mặc định → **exit 0**.
5. Không thêm dependency ngoài stdlib + `requirements.txt`. Giữ P1–P5 trong `CLAUDE.md`.
6. Cấm mở `~/Work/`, `~/Claude/Projects/`, `~/Data/`, `~/Downloads/`; cấm `.pdf .jpg .png .xlsx .docx .csv`.

## 🔴 LIVE BEFORE CLAIM — DÁN, ĐỪNG GÕ LẠI
🚨 **BỐN vòng liền** bạn khai lệnh không chạy được (`python` trần exit 127 · `python3 -m pytest` exit 1) và lệnh dispatch **thiếu prompt**. QA bắt cả bốn.

Cần lệnh + output **dán nguyên văn** + mã thoát cho:
- `build_claude_cmd('claude-opus-5','hi')` → chứng minh có `--model`
- `printf hi | … dispatch.py claude --result-json` (binary giả) → `served_model=claude-opus-5`, **không** warning sai
- Vendor **thật sự** không nhận cờ (`grok` hoặc fixture giả) → `served_model=null` + warning **đúng**
- `failover.py` có/không `--dry-run` với notifier giả → chứng minh khi nào gọi thật
- `grep -rn "send" commands/ README.md CLAUDE.md` sau khi sửa → chứng minh hết mâu thuẫn
- `$PY -m pytest tests/ -q` dòng cuối, **≥152**
- Phép **revert** lỗi 1 → test ĐỎ

## Trả lời
- `BAO-CAO-VONG9.md`, tiếng Việt, **≤50 dòng**, bảng phẳng. Ghi file ngay khi xong phần đầu.
- Không mở bài, không khen.
