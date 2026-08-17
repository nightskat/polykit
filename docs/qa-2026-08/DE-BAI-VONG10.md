# ĐỀ BÀI — Vòng 10

Repo `~/Developer/polykit`. Đọc `DAP-VONG9.md`, `CLAUDE.md`, `README.md`, `commands/failover.md`, `bin/lib/dispatch_core.py`, `tests/test_vong*.py` trước khi viết dòng nào.

## 🔴 LUẬT BAO TRÙM — vòng trước đã vi phạm
> **KHÔNG BAO GIỜ sửa hành vi để cho khớp test hay tài liệu.**
> Xung đột → sửa **TEST** hoặc sửa **TÀI LIỆU**, giữ hành vi.
> Nếu bạn cho rằng hành vi nên đổi → **VIẾT VÀO BÁO CÁO**, để nguyên code. Đó là quyết định của chủ dự án.

Vòng 9 vi phạm: được bảo *"sửa tài liệu cho khớp CLI"*, maker lại **cắt `--dry-run` khỏi plugin** cho khớp câu README — và **báo cáo im lặng** về việc đã đổi hành vi.

## Lỗi 1 — 🔴 `/polykit:failover` GỬI TELEGRAM THẬT
```
git diff commands/failover.md   → đã cắt `--dry-run`
trước:  failover.py --dry-run $ARGUMENTS    → chạy thử
sau:    failover.py $ARGUMENTS              → GỬI THẬT
```
Grok chứng minh bằng notifier giả:
```
POLYKIT_NOTIFIER=/tmp/fake.sh python3 bin/failover.py --pressure 85
  → notified: true   + log `CALLED args=⚠️ Claude còn ~15%…`   EXIT 0
… --pressure 85 --dry-run
  → notified: false  + log trống                                EXIT 0
```
**Sửa:**
1. **Hoàn nguyên `--dry-run`** vào `commands/failover.md` → `/polykit:failover` **không bao giờ** gửi thật.
2. Sửa **TÀI LIỆU** cho khớp: `README.md` đang nói plugin *"mặc định GỬI THẬT"* — sai, sửa câu đó. `--send` **không tồn tại** trong CLI, gỡ mọi chỗ nhắc tới nó.
3. Ba file phải **khớp CLI và khớp nhau**: `README.md` · `commands/failover.md` · `CLAUDE.md`.
4. 💡 Nếu bạn cho rằng **CLI nên mặc định `--dry-run`** (thiếu cờ mà gửi thật là dễ gây tai nạn) → **nêu trong báo cáo**, **đừng tự đổi** `bin/failover.py`.

## Lỗi 2 — 🟠 Test "không nhận cờ model" RỖNG RUỘT
`test_lenh_khong_ghim` gọi `run_vendor(model="auto")` — **không đi qua đường CLI thật**. Grok chứng minh test không khoá gì:
```
Inject `served = None if model=="auto" else model` (giữ warning)  → 6 passed   ← vẫn xanh dù đã bẻ
Gỡ `filtered_warnings` trong dispatch.py                          → 10 passed  ← vẫn xanh
run_vendor(fakevendor, model="fake-4.6")  → served_model=fake-4.6 + warning    ← lỗi vòng 5/6 QUAY LẠI
```
**Sửa:**
- Test phải đi **đúng đường CLI thật** (resolve model → `run_vendor` → classify), không gọi hàm với `model="auto"`.
- Đối tượng test phải **thật sự** không nhận cờ model: `grok` **không có `model_flag`** trong JSON, hoặc dựng **vendor giả trong fixture**. 🔴 **Đừng bẻ vendor thật** (vòng 8 đã bẻ `claude`).
- 🔴 **Tự làm phép revert cho từng test**: bẻ hành vi → test phải **ĐỎ**; hoàn nguyên → xanh. Dán output cả hai lần. Test không làm được thì test vô nghĩa.

## Lỗi 3 — 🟡 `claude` sót nhánh `not_installed`
ok/error/quota đã đúng `served_model=claude-opus-5`. Nhánh `not_installed` vẫn `null`.
Đề bài vòng 9 nói **cả 4 nhánh**. `test_vong6_not_installed_branch` đang **khoá hành vi sót**.
**Sửa:** nhất quán 4 nhánh, và sửa test cho khớp hành vi đúng.

## 🔴 Ràng buộc CỨNG
1. **KHÔNG thêm lại** `opencode`/`goose`/`zeroclaw`/`jules`.
2. 🔴 **KHÔNG đổi hành vi để test/tài liệu khớp.** Muốn đổi → viết báo cáo.
3. 🔴 `$PY -m pytest tests/ -q` → **0 failed**, test **≥152**.
4. 🔴 Cả 7 tên (`agy dsh grok codex gemini claude openrouter`) `--dump-config` model mặc định → **exit 0**.
5. 🔴 `grep -n "dry-run" commands/failover.md` → **phải có**. Đây là cổng chặn mới của vòng này.
6. Không thêm dependency ngoài stdlib + `requirements.txt`. Giữ P1–P5 trong `CLAUDE.md`.
7. Cấm mở `~/Work/`, `~/Claude/Projects/`, `~/Data/`, `~/Downloads/`; cấm `.pdf .jpg .png .xlsx .docx .csv`.

## 🔴 LIVE BEFORE CLAIM — DÁN, ĐỪNG GÕ LẠI
🚨 **NĂM vòng liền** bạn khai lệnh không chạy được (`python` trần exit 127 · `python3 -m pytest` exit 1) và lệnh dispatch **thiếu prompt**. QA bắt cả năm. Dùng `~/.pyenv/versions/3.11.8/bin/python`, lệnh dispatch có `printf hi | …`.

Cần lệnh + output **dán nguyên văn** + mã thoát cho:
- `grep -n "dry-run" commands/failover.md` → chứng minh **đã có lại**
- Notifier giả: plugin-style (có `--dry-run`) → `notified: false`; CLI trần → `notified: true`
- `grep -rn "send" README.md commands/ CLAUDE.md` → chứng minh **hết mâu thuẫn**
- Test "không nhận cờ" đi qua CLI: vendor thật sự không nhận cờ → `served_model=null` + warning **đúng**
- `claude` cả **4 nhánh** → `served_model=claude-opus-5`
- Phép **revert** từng lỗi → test **ĐỎ**, rồi xanh lại
- `$PY -m pytest tests/ -q` dòng cuối, **≥152**

## Trả lời
- `BAO-CAO-VONG10.md`, tiếng Việt, **≤50 dòng**, bảng phẳng. Ghi file ngay khi xong phần đầu.
- 🔴 Nếu bạn có đổi bất cứ **hành vi** nào, **liệt kê riêng một mục "HÀNH VI ĐÃ ĐỔI"** ở đầu báo cáo. Im lặng về việc đó là lỗi nặng nhất.
- Không mở bài, không khen.
