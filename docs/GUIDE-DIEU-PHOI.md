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
| `opencode run` gọi THẲNG im 10 phút, log 0 byte, không làm gì (02/11) | gọi qua `hermes -z … --provider opencode-go -m deepseek-v4.1-flash` (02/11 chạy được 2 lượt, ~3 phút/lượt); bỏ lượt im >5 phút |
| `codex exec` thiếu `< /dev/null` → treo "Reading additional input from stdin" | luôn `< /dev/null`; Hermes cũng vậy |
| Vendor tự báo "byte-identical" nhưng chỉ so phần nó KHÔNG sửa (Codex 02/11 ghi lại DOCX bằng ElementTree) | Claude nghiệm thu bằng phép kiểm độc lập; mẫu Word: `pgbank/soat-ho-so/shared/references/GUIDE_VA_MAU_DOCX_THAY_CHUOI.md` |
| Kiểm "sau 1 phút" (Tuan 02/11) | Monitor: `sleep 60` → `ps -p` + file mới tạo; rồi vòng chờ exit — đừng đợi stdout |
| `pgrep -f "hermes -z"` ra 0 dù đang chạy (02/11) | tiến trình thật là `~/.hermes/tools/python… -I -c …`; lấy PID từ `$!`/`jobs -p` lúc nohup, theo dõi bằng `kill -0 $PID` |
| Rà repo trước khi giao cloud: vendor tìm thấy PII đã commit ở 3/5 repo (02/11) | brief rà LUÔN kèm câu "repo có PII đã commit không (file:dòng)"; có → KHÔNG giao cloud, ghi `docs/CANH-BAO-PII-*.md` |
| `start_session target=cloud repository=…` từ phiên local báo "window needs reload" (02/11) | ghi brief ra file `CLOUD-<repo>.md`; Tuan mở New session → Cloud (env `default`: network Limited + package managers on, không secret) rồi dán |
| Cloud session KHÔNG báo về | giao 1 session local theo dõi PR: chạy test local + soát diff (02/11 bắt được file rác `rel.txt` trong PR polykit) |
| `dispatch.py agy --timeout 900` thoát ngay (02/11) | trần `--timeout` là 1–600 |
| Rà "toàn Mac" bằng 5 vendor song song (02/11, ~6 phút) | brief chung cấm mdfind/find toàn ổ + cấm mở ~/Work ~/Data Cache Hub Mail OneDrive; chia VÙNG: deepseek=~/Developer · glm=~/Claude .md · codex=PII lịch sử git · grok=scripts/LaunchAgents (vai đập) · agy=tài nguyên RAM. Brief mẫu: scratchpad phiên 02/11 `ra-mac/` |
| Grok suy "Mac cần LAN cơ quan" từ `scanbox.local` → SAI (Tuan: Mac không có LAN, sync tay) | ràng buộc offload thật = file local, Chrome profile thật, PII, GUI macOS; nghi phạm khi vendor nêu "cần LAN" |
| agy vs grok kết luận NGƯỢC về Hermes lên VM (RAM vs phụ thuộc) | giữ Hermes ở Mac (cần file local + Chrome thật); thủ phạm RAM là ~11 phiên `claude` mở cùng lúc (swap 6,6/8GB) — đóng phiên trước khi mua VM |
| Codex báo "CIF hard-code" trong test so-cai | mở xem: `'1234567890'` giả → giao được; regex hit ≠ PII, phải mở file |
| Vertex AI Search pilot (02/11): 72% vs pg-hoi 92% top-8 (314 câu, cùng 100 file) | giữ pg-hoi; đừng nạp kho QĐ lên Vertex. Bẫy chấm: doc id ngẫu nhiên → chấm theo trường `title`. Báo cáo + guide: `/Volumes/Cache Hub/pgbank-dedup/PILOT-VERTEX-2026-11.md`. Bật Discovery Engine API = Tuan bấm (gcloud bị chặn quyền) |

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

## Bắn việc code lên cloud từ phiên local (chốt 03/11/2026)
- **Vòng:** việc thật → cần code → `start_session target:cloud repository:nightskat/<repo>` → session mở PR → CI xanh → Claude local nghiệm thu (CI + diff + chạy lại) → Tuan merge.
- **Brief phải tự đủ:** cloud không đọc được scratchpad/file local → chép danh sách lỗi, tiêu chí "xong" đo được, "không merge", "ghi CHƯA CHẠY nếu chưa chạy".
- **Trước khi bắn:** push branch nền (cloud chỉ thấy remote). Rào PII đã bỏ 03/11 (Tuan quyết) — tiêu chí: bắn được + hiệu quả.
- **Bẫy:** lần gọi đầu có thể báo "app không nhận được duyệt" → gọi lại khi Tuan đang mở app. Cloud không hiện trong `list_sessions`, không báo khi xong → Tuan ghé claude.ai/code.
- **Đã chạy 03/11:** so-cai #1#2, docshift-core #26#27, vi-textmatch kind name, polykit CI 3-OS, vdub C3.

## Sửa PR hàng loạt bằng Codex local (03/11/2026)
1. Review: `codex exec --skip-git-repo-check -m gpt-6-sol -s read-only "<brief VERDICT MERGE|FIX|REJECT>"` → `<repo>-<n>.rev`.
2. Gắn review lên PR: `gh pr comment <n> --body-file` (cloud/vendor sau tự đọc, khỏi chép tay).
3. Sửa: script bash clone PR vào thư mục mới → `codex exec -s workspace-write "Sửa theo ../<repo>-<n>.review, mỗi lỗi + test chặn"` → commit + push cùng branch.
4. Nghiệm thu: CI xanh + live test việc thật (bank: dry-run trên ~/Work/pgbank) → merge. Lần review 2 không đưa review cũ.

## Ma trận ai × effort × việc (chốt 04/11/2026)

| Việc | Ai | Effort |
|---|---|---|
| Điều phối, nghiệm thu, soát số bank | Claude Opus 5.5 | low |
| Việc cơ khí, draft, prose VN, đọc dài | agy `gemini-3.8-flash-high` (luôn ghim `--model`) | high — gói cố định, effort cao không tốn tiền |
| Việc khó qua agy | agy `claude-opus-5-5-high` · `gemini-4-argon` (quota ít, chỉ review) | high |
| Code + adversarial review | Codex `gpt-6-sol` | high |
| Review nhanh | Codex `gpt-6-luna` | medium |
| Maker rẻ, tính toán/logic | DeepSeek V4.1 Flash | low (⛔ none 3/12; ⛔ V4-Pro kém Flash) |
| Bulk classify/tag | GLM-5.3-Flash | high (⛔ tính ngày/tiền) |
| Red-team, bắt số ảo | Grok 4.6 | low |
| VN polish ngắn | Sonnet 5.5 | medium (⛔ tự tính tiền) |
| OCR / PII | vnocr local | — |

Luật: lane trả theo token → low là điểm ngọt; lane gói cố định đang dư quota → effort cao được. Model sai thì đổi model / giao code tính, đừng bump effort.

### Quota snapshot 04/11/2026 (đo lại trước khi tin)
- Claude Max: tuần 68% → dự hết sáng thứ Sáu; chỉ plan + nghiệm thu.
- OpenCode Go: **tháng 90%**, dự chạm trần 07/11, gia hạn 08/11, Extra Usage TẮT → dừng hẳn (im lặng retry). Xem: opencode.ai/workspace → tab Go.
- DeepSeek API: $3,69 — `curl https://api.deepseek.com/user/balance -H "Authorization: Bearer $KEY"` (usage thật bằng code).
- Codex: vừa reset. agy: dư nhất.
- Claude Code cloud credit: $56/$250, **hết 14:59 05/11** → dùng nốt cho repo có CI.
- GCP: Developer Program ≈1,66tr VND (toàn GCP, Vertex `global`) + trial 26,1tr (chỉ Vertex AI Search).
- Thứ tự rót việc đến 08/11: **agy → Codex → DeepSeek API → Grok → Vertex**; Go để dành việc gấp.

## Khi Claude outage (chốt 04/11/2026)

| Vai | Bình thường | Claude sập → |
|---|---|---|
| Main/orchestrator | Opus low | **Codex `gpt-6.1-sol`** (sub) |
| Maker cơ khí | Sonnet/DeepSeek | Hermes → `deepseek-v4.1-flash` **low** |
| QA red-team | Grok | Grok 4.6 **low** qua Hermes |
| Prose VN / doc dài | Sonnet | agy `--model gemini-3.1-pro-preview` |
| Tính tiền/ngày | Opus | DeepSeek low **+ tính lại bằng code**; cấm GLM, cấm effort none |
| Hồ sơ KH | Claude host | Local (vnocr, pg-hoi) |

App thay Claude desktop: Codex CLI/app → agy IDE → Hermes chat (⛔ không nhét `sk-ant-`) → Gemini app/NotebookLM cho hỏi nhẹ.

Bẫy:
- agy lane Claude (Opus/Sonnet) vẫn do Anthropic phục vụ model → outage cấp model thì chết theo; dùng lane Gemini.
- Trước khi trông vào agy: `agy models < /dev/null` (state 03/11 báo `stale`).
- pg-hoi chạy local, không phụ thuộc Claude.
