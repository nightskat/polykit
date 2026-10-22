# Grok review vòng 3

- Calls tất cả qua python bin/dispatch.py grok --model grok-4.7 --timeout 600 --result-json; prompt/result files cạnh tài liệu này.
- Full diff review (evidence/2026-10-22/lo-v3-review.md): timeout, chỉ lời mở đầu; không coi là review hoàn tất.
- Gate nguồn nhúng 24KB (evidence/2026-10-22/lo-v3-review-gate.md): timeout rỗng; chia tiếp, đã ghi BUGS trước retry.
- Gate snippet ngắn (evidence/2026-10-22/lo-v3-review-gate-small.md): status=ok, không thấy finding thực trong phạm vi manifest/path/hash gate. Không mở rộng thành chứng nhận toàn repo/TOCTOU/sandbox; reviewer chỉ thấy snippet.
- Auth/scorer (evidence/2026-10-22/lo-v3-review-auth-score.md): status=ok, 3 findings High như bảng. Điều phối kiểm lại và giao Hermes sửa qua dispatch, không tự viết code sản phẩm.

| Finding | Xử lý | Kiểm chứng |
|---|---|---|
| Failure reason 'login required'/'unauthorized: …' không khớp exact nên ok cũ thắng | So marker có biên từ trên status/reason/error/stderr/summary, chuẩn hoá dấu phân cách; có negative phủ định | tests/test_bug14_go_probe.py: newer auth failure và biến thể marker |
| Failure now+1s bị drop, ok cũ trong TTL thành ready | Chính sách 5s skew chỉ cho failure fail-closed; future success không promote, quá skew bỏ, không poison dài hạn | Test boundary 5s/5s+1µs, future success/ngoài cửa sổ |
| role tool_result type text bị chấm như câu trả lời, contamination false | Shared marker role/type chứa tool; assistant text allowlist; runner contaminated_tools loại toàn call khỏi điểm | tests/test_vision_bench_score.py: JSONL tool_result chứa answer đúng vẫn score0/no predictions |

- Bổ sung điều phối: metadata auth sai kiểu .strip crash, legacy wrong model; đã thêm type/catalog guard và tests.
- Bổ sung điều phối: PDF caller output_dir chứa stale/symlink có thể lẫn vào attachment; đã reject output_dir public, fresh private conversion + trần/page sequencing/regular PNG tests. Live hardened DeepSeek PDF 8/9, status ok.
- Bổ sung điều phối: table label cross-field leak; prompt bảng chỉ tọa độ, đã chạy lại cả hai model. Model output không được bịa/điền từ GT.
- Unit tiền hậu tố VND/VNĐ/đ là tương đương giá trị số theo brief; whitelist test thay vì strip mọi chữ. Các vòng điểm cũ và rescore đều giữ nguyên nguồn và nhãn.
- Điều phối tự chạy acceptance: 1046 passed in 21.42s; git diff --check cho bin/tests/bench sạch. Raw logs/prompts/diff giữ nguyên whitespace nguồn nên full diff check có cảnh báo; không sửa evidence để làm đẹp. Không claim Grok đã tái-review toàn bộ code cuối sau từng fix; regression + live evidence là bằng chứng nghiệm thu sửa lỗi.
