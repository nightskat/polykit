# Brief vòng 2 cho Sol — mở lane Go có điều kiện + chốt báo cáo

Tiếp nối BRIEF-SOL.md (đọc lại phần quy trình maker/fallback/review). Nhánh feat/hermes-opencode-vision, 21 commit, 730 test pass.

## Quyết định mới của Tuan (22/10/2026)
opencode/hermes ĐƯỢC chạy không sandbox CHỈ với việc code / dữ liệu không PII. PII vẫn chặn.

## Việc
0. Commit 2 file docs đang dở (README.md, commands/dispatch.md) nếu nội dung đúng.
1. Thay chặn `sandbox_unsupported` bằng cổng có điều kiện:
   - Dispatch opencode/hermes cần cờ tường minh (vd `--data-class code-nopii`), không có cờ → vẫn blocked như cũ.
   - Có cờ mà input có đính kèm ảnh/PDF hoặc cờ dữ liệu nhạy cảm/vision thật → blocked.
   - Chạy thêm kiểm `pg-redact check` (nếu có trên máy) trên prompt; phát hiện PII → blocked. Không có pg-redact → ghi warning, vẫn chặn khi có đính kèm.
   - Result JSON ghi rõ `unsandboxed: true` + data_class.
   - Cổng vision với dữ liệu thật GIỮ NGUYÊN chặn.
   Maker agy, fallback DeepSeek; test bắt buộc cho từng nhánh.
2. Grok-4.7 review riêng phần này (bypass cờ, PII lọt).
3. LIVE TEST với prompt vô hại tổng hợp: opencode × {deepseek-v4.1-flash high, glm-5.3-flash max}, hermes × default, model *-free tường minh 1 lần (ghi kết quả), contributor → blocked, không cờ → blocked. Vision: ảnh tổng hợp docs/plans/evidence/2026-10-22/vision-synthetic.png qua opencode -f với deepseek (tách trang nếu PDF) → so đúng/sai số trong ảnh.
4. Ghi docs/plans/BAO-CAO-2026-10-22.md (≤60 dòng): tất cả commit 2 vòng, test count, finding grok + xử lý, bảng live test (lệnh → kết quả thật), việc treo. Chưa chạy thì ghi CHƯA CHẠY.

Cấm: push, merge main, sửa ~/.hermes ~/.codex credential, đụng dữ liệu khách hàng, model *-contributor.
Nếu Codex lại 429: dừng gọn, ghi trạng thái dở vào BAO-CAO (đừng để trống).
