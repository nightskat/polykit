# Báo cáo vòng 3 — 22/10/2026
- Nhánh feat/vision-bench, base 7fb0920. Điều phối không viết code sản phẩm; mọi maker/reviewer qua python bin/dispatch.py của PolyKit.
- Commit generator: cf6342b (PIL/manifest) và dadbbaf (GT từng ô, bỏ gợi đáp án); maker agy.
- Commit BUG-14: 23a51d4 (shared probe/evidence), 223d858 (review fixes); maker agy/Hermes.
- Commit gate: 64f5fb9 (hash pin, synthetic-only, PDF private, delimiter); maker agy/Hermes.
- Commit runner/scorer: 0c390b6 (typed, JSONL contamination, prompt sạch); maker agy/Hermes.
- Commit báo cáo/evidence: xem git log -1 -- docs/plans/BAO-CAO-VONG3.md.
- Test điều phối: baseline 793 passed/16.51s; acceptance cuối 1046 passed/21.42s; diff --check cho bin/tests/bench sạch. Raw evidence giữ nguyên whitespace (full diff check có cảnh báo).
- Dataset: 6 PNG + PDF ảnh 2 trang, seed42, 142 trường, manifest schema1 + SHA256; chỉ dữ liệu tổng hợp.
- Dispatch chỉ nhận ảnh/PDF synthetic nằm đúng root bench, manifest/registry/hash khớp; dữ liệu thật vẫn chặn. Hermes attachment chưa mở.
- Bench chính đã loại gợi nhãn hàng khỏi prompt; chỉ row/column. Hai model ×6 PNG đều inference thành công, không thấy tool-event.
| Vòng sạch | Đúng trường | Riêng số tiền | Thời gian | Dispatch |
|---|---:|---:|---:|---:|
| DeepSeek-v4.1-flash high | 137/142 (96,48%) | 59/59 | 111,53s | 6 |
| GLM-5.3-flash max | 136/142 (95,77%) | 59/59 | 183,12s | 6 |
| vnocr raw Apple Vision (*) | phục hồi 43/142 token (30,28%) | 29/59 token | 1,91s | 0 cloud |
- (*) Token recovery KHÔNG phải field accuracy/gán ô. Không giả làm so sánh parser ngang hàng; mỗi model đúng 94 trường mà raw vnocr không phục hồi được trên bộ này.
- vnocr có sẵn và đã chạy thật; thêm --cross-check-mlx chạy 6 trang, exit1 needs_human_reading vì 5 trang bất đồng số; không gọi là engine chưa chạy/thành công tự động.
- PDF DeepSeek: tách pdftoppm rồi gửi 2 ảnh; bản harden 8/9, 19,91s/1 lượt. GLM direct PDF: upstream HTTP400, không inference, N/A accuracy; PNG trang5/6 tương ứng 7/9.
- Tổng vision dogfood cả vòng lỗi/gợi nhãn/retry: DeepSeek21 dispatch/14 inference; GLM20/12. Đơn vị quota/billing thực chưa biết.
- Kết luận: DeepSeek đáng làm tầng đối chiếu SỐ trên synthetic này; không tự động chốt hồ sơ. Cả hai vẫn nhầm O/0, l/1; mã và dấu tiếng Việt còn sai. Chỉ 1 seed/6 trang, chưa suy rộng hồ sơ thật.
- Model/effort ghi là yêu cầu; served_model chưa xác nhận. Harness unsandboxed, cwd trống và lọc tool-event không phải sandbox bảo mật.
- BUG-14 Go: doctor và dispatch chung evidence TTL1h; failure mới thắng, future success không promote; catalog không chứng minh auth. Live cả opencode/hermes ready có timestamp.
- Dogfood đã ghi docs/BUGS.md trước fallback: timeout, syntax gate dang dở, mất cờ synthetic ở builder, -f nuốt prompt, PDF output stale/symlink, scorer/tool_result và gợi đáp án chéo.
- Nhân viên/reviewer: 23 lượt result JSON, 12 ok/11 timeout. Timeout có thể đã ghi code; điều phối kiểm file/test trước kết luận. Lô vượt600s được chia tiếp, không nới trần.
- Khi dispatch worktree lỗi syntax, dùng bản PolyKit cf6342b giải nén scratch để dispatch maker sửa đúng worktree; không gọi CLI nhân viên trực tiếp.
- Grok-4.7: full diff và gate24KB timeout; auth/scorer trả3 findings, gate snippet ngắn trả không thấy finding thực. Ba findings đã sửa + regression; không claim reviewer tái-review toàn repo cuối.
- Finding sửa: auth failure reason không exact; failure lệch5s; role tool_result false-correct. Bổ sung type guard metadata, catalog legacy, PDF private isolation và currency whitelist.
- Toolkit README đã thêm riêng mục PolyKit (trước đó không có mục này): 9 vendor, default mới, code-nopii; không sửa mục khác.
- Không push, không merge main, không xoá worktree, không sửa credential, không dữ liệu khách hàng, không model contributor. Không gọi Codex child nên không gặp Codex429.
- Treo: GLM PDF direct HTTP400; free explicit cũ chưa retest; chưa baseline field-map Apple Vision+MLX; chưa độ ổn định nhiều seed; chưa đối kháng local filesystem/PII production. Không mở lane ngân hàng.
- Chi tiết: BENCH-VISION-2026-10-22.md, REVIEW-GROK-VONG3.md; raw_calls/prompts/run_summary dưới bench-v3-*-final/, PDF hardened, doctor-v3-acceptance.txt, live-v3-negative.json, tests-v3-acceptance.txt.
