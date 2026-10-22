# Guide điều phối — cho vendor/agent làm tiếp PolyKit

> Viết 22/10/2026 sau 3 vòng triển khai (v0.11.2 → 0.12.0). Đọc file này TRƯỚC khi nhận việc ở repo.
> Chi tiết bằng chứng: `docs/plans/BAO-CAO-2026-10-22.md`, `BAO-CAO-VONG3.md`, `BENCH-VISION-2026-10-22.md`, `docs/plans/evidence/2026-10-22/`.

## 1. Mô hình làm việc (đã chạy thật, 34 commit, 0 lần hỏng main)

| Vai | Ai | Gọi thế nào |
|---|---|---|
| Phó phòng (giao, gỡ vướng, nghiệm thu) | Claude (session chính) | — không tự gõ code |
| Điều phối | Codex `gpt-6.1-sol` low **qua Hermes** | `hermes -z "<đọc BRIEF.md>" --provider openai-codex -m gpt-6.1-sol --reasoning low < /dev/null` |
| Maker | agy `gemini-3.8-flash-high` | `python3 bin/dispatch.py agy --prompt-file lo-N.md --cd "$PWD" --timeout 600 --result-json` |
| Fallback maker | DeepSeek v4.1 flash high qua Hermes/OpenCode Go | `python3 bin/dispatch.py hermes --data-class code-nopii --prompt-file lo-N.md ...` |
| Reviewer | `grok-4.7` qua Hermes (`--provider xai-oauth`) | review adversarial diff, mỗi vòng |

Nguyên tắc: vendor nào Hermes cầm (openai-codex, xai-oauth, opencode-go, openrouter, copilot) → gọi QUA Hermes. agy thì gọi CLI riêng.

## 2. Quy trình một vòng

1. Brief (`BRIEF-SOL*.md`, lưu ở `docs/plans/evidence/2026-10-22/`) = mục tiêu + quyết định đã chốt + cấm + "429 thì ghi trạng thái dở".
2. Điều phối chia **lô nhỏ ≤10 phút**, 1–3 file + test, ghi `LO-*.md`.
3. Maker làm → **điều phối tự chạy pytest** (không tin maker) → xanh mới commit, message ghi tên maker.
4. Maker hỏng/timeout 2 lần → fallback DeepSeek.
5. Hết lô → Grok review diff → finding thật thành lô sửa riêng.
6. Live test bằng prompt/ảnh **tổng hợp** → báo cáo ≤60 dòng, ô chưa chạy ghi `CHƯA CHẠY`.
7. Claude nghiệm thu: chạy lại pytest, tự thử vài ca chặn, đối chiếu báo cáo với `git log`.

## 3. Bẫy đã dính (đọc kỹ)

| Bẫy | Cách tránh |
|---|---|
| `hermes -z` chỉ in khi KẾT THÚC → tail log không thấy gì | theo dõi `git log` + `ps` (tiến trình con) thay vì stdout |
| Terminal tool của Hermes trần 180s; agy lô dài bị cắt (3/4 lô vòng 2) | lô nhỏ; agy `--print-timeout`; chạy nền + poll log; có sẵn fallback |
| Codex 429 giữa chừng (reset sau ~2h) | brief bắt ghi trạng thái dở vào BAO-CAO; hẹn giờ chạy lại vòng sau |
| Codex/Hermes chạy trong sandbox → `--help`/`models` exit 1 → ghi nhầm "CHƯA KIỂM" | Claude kiểm lại NGOÀI sandbox trước khi tin |
| `dispatch.py --result-json` lẫn dòng log trước JSON → `json.load` vỡ | đọc dòng JSON cuối; (bug ứng viên, chưa sửa) |
| `--` thiếu sau `-f` → 7/7 lượt vision hỏng | đã sửa; giữ test |
| Prompt bench gợi tên nhãn → model đoán thay vì đọc | vòng "sạch" chỉ gửi id/hàng/cột, dùng vòng sạch làm kết luận |
| Plugin không cập nhật dù đã push | Claude Code so **version**: phải bump `.claude-plugin/plugin.json` rồi `claude plugin marketplace update polykit && claude plugin update polykit@polykit`, restart |
| Merge "vào main" nhưng checkout đang ở `ship-prep` | `git branch --show-current` TRƯỚC mỗi merge |
| Repo **PUBLIC**, evidence do agent sinh (raw call, log) | quét key/PII TRƯỚC push, không phải sau |
| Merge từ worktree: file plan chưa track trùng tên | so nội dung rồi mới bỏ bản chưa track |

## 4. Quyết định đã chốt (đừng hỏi lại Tuan)

- Default: codex `gpt-6.1-sol` low · agy `gemini-3.8-flash-high` (+hồ sơ `kho`=argon-high, `claude`=sonnet-5-5-medium) · opencode/hermes `deepseek-v4.1-flash` high (+`glm-5.3-flash` max chọn tay) · grok reviewer `grok-4.7`.
- `*-contributor` (vendor train trên dữ liệu): **chặn cứng** mọi đường. `*-free`: chỉ chọn tường minh, không default/auto/failover.
- opencode/hermes **không sandbox**: chỉ chạy khi `--data-class code-nopii`; đính kèm/vision thật/PII vẫn chặn. `data_class` là LỜI KHAI, không phải ranh giới bảo mật — agent vẫn đọc được file ngoài repo.
- Vision: tầng ĐỐI CHIẾU số cho trang vnocr hỏng, không thay vnocr, không nguồn quyết định. Mã kiểu `O0l1` vẫn đọc tay.
- ZDR DeepSeek trên OpenCode Go gia hạn theo tháng, hết **31/10/2026** → kiểm lại trang `opencode.ai/go`.

## 5. Kết quả số để tham chiếu

- Test: 275 → 793 (vòng 1–2) → 1046 (vòng 3).
- Bench vision 6 trang tổng hợp / 142 trường: DeepSeek 96,5%, GLM 95,8%, ô tiền 100% cả hai; mã `O0l1` 60%. Chưa phải độ chính xác hồ sơ thật.
- Quota Go ước tính /5h: DeepSeek ~34.670 lượt, MiMo ~30.100, GLM-flash ~6.320.

## 6. Việc còn treo

- `--result-json` lẫn log (ghi vào `docs/BUGS.md`).
- `*-free` chọn tay: qua cổng nhưng vendor lỗi server — chưa inference thành công.
- GLM gửi PDF trực tiếp: HTTP 400 upstream.
- `served_model` chưa CLI nào xác nhận → luôn null.
- Bench vision trên trang khó hơn (con dấu, chữ chồng, giấy thật mô phỏng).
- Sandbox thật (container) cho lane Go nếu muốn mở với dữ liệu nhạy hơn.
