# Brief cho Sol (điều phối) — triển khai plan PolyKit

Bạn là ĐIỀU PHỐI, không tự viết code. Repo: thư mục hiện tại (git worktree nhánh feat/hermes-opencode-vision). Plan: docs/plans/2026-10-22-them-hermes-opencode.md (+ bench.csv, go-page.md, opencode-go-verbose.txt, agy-models.txt cạnh nó). Đọc CLAUDE.md, plan, docs/BUGS.md trước.

Quyết định đã chốt (Tuan): default codex gpt-6.1-sol low; opencode+hermes default deepseek-v4.1-flash high, hồ sơ glm-5.3-flash max; chặn cứng *-contributor; *-free CHO chọn tường minh, không bao giờ default/auto/failover; agy default gemini-3.8-flash-high + hồ sơ phụ; Lane VISION với cổng PII chặn mặc định.

## Quy trình
1. Chia plan thành các lô NHỎ (mỗi lô ≤ ~10 phút làm, 1-3 file + test). Ghi danh sách lô vào docs/plans/LO-TRIEN-KHAI.md. Ưu tiên: (1) model_policy + test, (2) resolver/default + sửa codex, (3) adapter opencode/hermes, (4) doctor/failover/watcher, (5) vision + cổng PII, (6) docs.
2. MAKER mỗi lô — gọi agy CLI (Hermes không cầm sub agy):
   `agy --model gemini-3.8-flash-high --dangerously-skip-permissions --add-dir "$PWD" --print-timeout 900s --print "$(cat lo-N.md)" < /dev/null`
   Brief từng lô viết ra file lo-N.md: mục tiêu, file được sửa, test phải pass, lệnh test.
   Nếu terminal tool của bạn có trần thời gian ngắn hơn, chạy agy nền ghi log (`> log 2>&1 &`) rồi poll file log.
3. FALLBACK khi agy lỗi/hết quota/2 lần không qua test: `hermes -z "$(cat lo-N.md)" --provider opencode-go -m deepseek-v4.1-flash --reasoning high < /dev/null`.
4. Sau MỖI lô tự chạy: `~/.pyenv/versions/3.11.8/bin/python -m pytest tests/ -q`. KHÔNG tin maker nói "đã chạy test" (agy từng bịa kết quả pytest). Đỏ → trả lại maker kèm lỗi.
5. Xanh → commit lô (message tiếng Việt ngắn, kèm dòng `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` KHÔNG cần — chỉ ghi tên vendor maker trong message).
6. REVIEW sau khi xong hết lô: `git diff <base>..HEAD > /tmp/...diff`, rồi
   `hermes -z "<yêu cầu adversarial review: bug, bypass chốt chặn contributor/free, cổng PII vision, test giả>" --provider xai-oauth -m grok-4.7 --reasoning high < /dev/null` (đưa diff qua file, dặn grok đọc file). Sửa finding thật qua maker, chạy lại test.
7. LIVE TEST (bạn tự làm): doctor.py; dispatch thật với PROMPT VÔ HẠI tổng hợp cho: opencode × 2 hồ sơ, hermes × default, codex default, agy default; thử model contributor → phải blocked; thử *-free không tường minh → blocked; vision với 1 ảnh TỔNG HỢP tự tạo (vd PIL vẽ số tiền giả) qua opencode -f → so đúng/sai; vision với cờ dữ liệu thật mà không xác nhận → blocked.
8. Ghi BÁO CÁO docs/plans/BAO-CAO-2026-10-22.md (≤60 dòng): lô nào xong/commit hash, test count, finding grok + xử lý, bảng live test (lệnh → kết quả thật), việc còn treo. Không bịa: chưa chạy thì ghi CHƯA CHẠY.

## Cấm
- Không đụng dữ liệu khách hàng/PGBank, không đọc ngoài repo trừ CLI help. Không push, không merge vào main, không sửa ~/.hermes, ~/.codex, credential.
- Không dùng model *-contributor ở bất kỳ bước nào.
