# Brief vòng 3 cho Sol — dùng CHÍNH PolyKit để làm việc

Repo: worktree nhánh feat/vision-bench (từ main 7fb0920, 793 test). Đọc CLAUDE.md, docs/plans/BAO-CAO-2026-10-22.md, BRIEF-SOL.md (quy trình cũ) — nhưng vòng này mọi lượt gọi nhân viên PHẢI qua PolyKit:
- Maker: `python3 bin/dispatch.py agy --prompt-file lo-N.md --cd "$PWD" --timeout 600 --result-json`
- Fallback: `python3 bin/dispatch.py hermes --data-class code-nopii --prompt-file lo-N.md --cd "$PWD" --timeout 600 --result-json`
- Review: `python3 bin/dispatch.py grok ...` (grok-4.7).
Đọc result JSON (status/reason/warnings). Mỗi lần PolyKit cản đường vô lý, timeout, báo sai → GHI vào docs/BUGS.md (đó là dữ liệu dogfood quý nhất vòng này) rồi mới đi đường vòng. Lô quá 600s → chia nhỏ hơn.
Python: ~/.pyenv/versions/3.11.8/bin/python. Tự chạy pytest sau mỗi lô; không tin maker.

## Việc A — Bench vision trên trang khó (ưu tiên)
Mục tiêu: trả lời "vision có bù được vnocr ở trang khó không" bằng số đúng/sai.
1. Mở đường dispatch cho vision TỔNG HỢP: ảnh chỉ được nhận nếu nằm trong thư mục bench riêng (vd `bench/vision/synthetic/`) và có manifest do generator của repo sinh (hash khớp). Ngoài điều kiện đó vẫn vision_blocked. Dữ liệu thật vẫn chặn như cũ. Có test.
2. Generator (PIL, deterministic seed) sinh ~6 trang mô phỏng ĐÚNG chỗ OCR hay hỏng ở BCTC/hồ sơ ngân hàng VN: bảng nhiều cột hẹp có số dạng 1.234.567.890; số âm trong ngoặc (12.345); chữ số dễ nhầm 0/O 1/l 5/6/8 và 2026↔2006; scan mờ/nghiêng/nhiễu/JPEG xấu; chữ tiếng Việt có dấu; một trang PDF nhiều trang (tách trang trước khi gửi model không nhận pdf). Ground truth JSON từng ô. TOÀN BỘ dữ liệu bịa, không tên người thật.
3. Chấm: so từng trường theo KIỂU DỮ LIỆU (số tiền so giá trị số, ngày so ngày, mã so chuỗi chính xác) — không dùng difflib, không tin điểm tự tin model.
4. Chạy qua dispatch: opencode deepseek-v4.1-flash high, opencode glm-5.3-flash max (nhận pdf trực tiếp — thử cả 2 cách), và nếu có sẵn trên máy thì `vnocr` cục bộ làm baseline (kiểm `command -v vnocr`; nếu không chạy được thì ghi CHƯA CHẠY, không bịa).
5. Báo cáo docs/plans/BENCH-VISION-2026-10-22.md: bảng model × loại lỗi (% đúng), thời gian, lượt quota; kết luận ngắn: model nào đáng làm tầng đối chiếu, loại lỗi nào vision cũng hỏng.

## Việc B — BUG-14
doctor báo opencode/hermes `auth_unverified` dù dispatch live chạy được. Sửa để doctor dùng chung cơ sở probe với dispatch; regression test.

## Việc C — Dọn + sổ sách (cuối cùng)
- Cập nhật ~/Claude/Toolkit/README.md mục PolyKit: 9 vendor, default mới (codex gpt-6.1-sol low; opencode/hermes deepseek-v4.1-flash high, cờ --data-class code-nopii). Chỉ sửa mục PolyKit.
- KHÔNG xoá worktree nào (Claude làm).

## Kết thúc
Grok review diff vòng 3. Báo cáo tổng ≤60 dòng: docs/plans/BAO-CAO-VONG3.md (commit, test, bench kết quả, bug PolyKit phát hiện khi dogfood, treo). Codex 429 → dừng gọn, ghi trạng thái dở.
Cấm: push, merge main, sửa credential, dữ liệu khách hàng thật, model *-contributor.
