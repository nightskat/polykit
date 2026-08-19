# PolyKit — sổ bug

> **Luật**: agent nào dùng PolyKit mà thấy hành vi sai thì ghi vào đây NGAY, kèm lệnh nguyên văn
> và cái đã ĐO được. Sửa được trong phiên thì sửa luôn và ghi bằng chứng. File này **phải nằm
> trong git** — 18/08 nó từng nằm untracked một ngày, không ai thấy.
> Trạng thái: 🔴 MỞ · ✅ ĐÃ SỬA · ⚪️ ĐÓNG (không phải bug).

## Phiên 18/08/2026

> Dispatch thật: soát chéo 1 bộ hồ sơ tín dụng, prompt 37.073 byte (5 file Word đã thay PII).
> Lệnh: `cat full_prompt.txt | python3 bin/dispatch.py codex gpt-5.5 --timeout 580 --result-json`

## ✅ Chạy đúng — kết quả tốt
`status=ok`, `exit_code=0`, `vendor=codex`, `model=gpt-5.5`, `served_model=gpt-5.5`, `warnings=[]`.
Nội dung: **8 phát hiện, hội tụ 4/4 lỗi chính** mình đã tự bắt (số tiền 450 vs 300, lãi suất
9,9% vs 12%, mục đích copy nhầm hồ sơ, số HĐTC cụt) — **0 ảo giác**, đúng định dạng yêu cầu.
Chi phí ~1 lượt codex thay vì tự đọc lại 5 file bằng model chính. **Đây là ca dùng đúng của PolyKit.**

## ⚪️ BUG-1 — dòng `[polykit] served:` không in ra stderr → **KHÔNG phải bug** (đóng 19/08)

Memory `reference_polykit_silent_degrade` ghi *"dòng `[polykit] served: <model>` in ra **stderr**"*.
Đo lần này: `2> codex_stderr.txt` → **file 0 byte**. Dòng `served:` không xuất hiện ở đâu cả.

Không nguy hiểm (field `served_model` trong `--result-json` vẫn có và đúng), nhưng:
- ai chạy **không** kèm `--result-json` thì **mất hẳn** dấu vết model thật;
- memory hiện đang mô tả sai hành vi → cần sửa memory HOẶC trả lại dòng stderr.

**Kết luận 19/08** — đọc `bin/dispatch.py:196`: dòng đó chỉ in **khi `served_model != resolved_model`**.
Lượt 18/08 gọi `codex gpt-5.5` và được phục vụ đúng `gpt-5.5` → trùng nhau → im lặng **theo thiết kế**.
Tái lập 19/08 với `dsh` (`served=resolved=deepseek-v4-pro`): stderr cũng không có dòng `served:`. Nhất quán.
⇒ Không sửa code. Đã sửa **tài liệu**: `commands/dispatch.md` nói rõ dòng này chỉ xuất hiện khi model
thật KHÁC model yêu cầu, và `--result-json` mới là nguồn chính thức. Memory mô tả sai cần sửa theo.

## ✅ BUG-2 — prompt dài không có đường truyền file (đã sửa 19/08)

`dispatch.py` chỉ nhận prompt qua **stdin**. Với prompt 37 KB thì `echo "<prompt>" |` như
`commands/dispatch.md` hướng dẫn là **không dùng được** (quoting + xuống dòng + dấu tiếng Việt).
Phải tự viết `cat file | python3 …`.

**Đã sửa 19/08**: thêm `--prompt-file <path>` vào `bin/dispatch.py`. File không đọc được hoặc rỗng
→ exit 2, chặn **trước** khi gọi vendor. `commands/dispatch.md` viết lại: stdin cho prompt một dòng,
`--prompt-file` cho prompt dài/nhiều dòng/có dấu.
Bằng chứng: `tests/test_prompt_file.py` (3 test) + **live test thật** qua `dispatch.py dsh
--prompt-file` với prompt tiếng Việt nhiều dòng có dấu ngoặc kép → `status=ok`,
`served_model=deepseek-v4-pro`, stdout `3` (đúng: *"Đường vô xứ Nghệ quanh quanh"* có 3 chữ mang
dấu thanh — ờ, ứ, ệ), và file `dem.py` + `ketqua2.txt` có thật trong thư mục.

## 🔴 QUAN SÁT-3 — không có cổng chặn PII
`dispatch.py` gửi thẳng stdin ra vendor, **không kiểm tra gì**. Luật lane PGBank bắt phải qua
`pg-redact check` exit 0 trước khi gửi — nhưng chính `pg-redact` đang hỏng với văn xuôi
(xem `~/Claude/Build/tools/pg-redact/BUGS_2026-08-18.md`), nên luật đó **không thi hành được**
bằng máy, chỉ còn kỷ luật tay.
⇒ Nếu sau này vá pg-redact, đáng cân nhắc `dispatch --require-clean` gọi `pg-redact check`
làm cổng cứng. **Chưa làm bây giờ** — luật 3 lần đau, đây mới là lần 1.

## ⏱️ Số liệu
- Prompt 37 KB · timeout đặt 580s (trần cứng 600s vẫn đúng như memory ghi) · chạy trọn, không chạm trần.


## Phiên 19/08/2026

### ⚪️ Bản cài và repo đã tách nhau (đã hoà, không phải bug code)
`~/.claude/plugins/marketplaces/polykit` đứng ở `fa09257` trong khi repo đi thêm 15 commit —
bản cài kẹt ở kiến trúc trước `lib/vendor_config.py`, `vendors.json` còn schema v1, nên
**không có vendor `dsh`** dù registry repo đã có. Thêm nữa nó mang sửa đổi chưa commit của
phiên 18/08 (chính là file bug này).
Đã xử: đóng gói việc chưa commit thành nhánh `port/2026-08-18-docs`, merge về repo (`daf3faf`),
rồi đồng bộ một chiều repo → bản cài. 153 test xanh.
⇒ Bài học: **sửa trong bản cài là sửa vào chỗ sẽ bị ghi đè**. Sửa ở `~/Developer/polykit`, rồi đồng bộ.

### ✅ Adapter mỗi vendor trôi vì populate là HÀNH ĐỘNG, không phải TRẠNG THÁI (sửa 19/08)
Đo được: Claude ghim cache ở commit 03/08 · Codex ghim bản 14/07 (`0.2.1+codex.local`) ·
Gemini dùng extension `cross-cli-dispatch` v0.1.0 **ngày 05/05**, không gọi PolyKit dòng nào và
còn quảng cáo model đã chết (`o3`, `o4-mini`) · Grok chưa cài · agy chưa có.

Cái thiếu không phải "chạy populate lần nữa" mà là **một lệnh kiểm tra được**.
⇒ `bin/populate.py`: `--check` in bảng 5 vendor + cờ lệch, `--apply` sinh adapter và gọi lệnh
update của từng CLI. Adapter được SINH từ `commands/*.md`, không sửa tay.

Điểm mấu chốt phát hiện được lúc làm: **Claude Code không chạy thư mục marketplace** mà chạy
bản chép ở `cache/polykit/polykit/<ver>/` ghim theo `gitCommitSha`. Test vào `marketplaces/…`
là test nhầm thứ hai — đã dính đúng lỗi này một lần trong phiên.
Codex/Gemini không có vấn đề đó: adapter chỉ là CHỮ, engine gọi thẳng `bin/dispatch.py` của repo.
