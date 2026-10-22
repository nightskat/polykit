# PolyKit

Claude Code plugin gom multi-vendor CLI tooling: **doctor** (trạng thái vendor), **dispatch** (giao task cho vendor), **failover** (cảnh báo quota), **watcher** (theo dõi model/version). Python-first, chạy macOS / Windows / Linux. Vendor thiếu = degrade, không crash.

## Prereqs
- **git**, **Python 3.9+**, **Claude Code**.
- Vendor CLIs = tùy chọn (cài cái nào dùng cái đó). PolyKit tự detect + báo cái nào chưa auth.
- Không cần `pip install` gì — chỉ stdlib. (`platformdirs` tùy chọn để path chuẩn hơn.)

## Cài (Mac & Windows như nhau)
```
claude plugin marketplace add https://github.com/nightskat/polykit.git
claude plugin install polykit@polykit
```
Xong. Mở session mới, gõ `/polykit:doctor` xem trạng thái.

## Lệnh
| Lệnh | Làm gì |
|---|---|
| `/polykit:doctor` | Bảng trạng thái mọi vendor (`ready` / `installed_not_authed` / `auth_unverified` / `not_installed` / `quota_capped`) + hint phù hợp |
| `/polykit:dispatch <vendor> [model] -- <prompt>` | Giao task; vendor thiếu → degraded result, không lỗi. `--timeout` tối đa **600 giây** — truyền cao hơn bị chặn ngay ở cổng validate, không chạy |
| `/polykit:failover --pressure N` | Quota còn thấp → gợi ý handoff (chỉ chạy thử do plugin luôn gắn `--dry-run`) |
| `/polykit:watcher` | Diff model/version vendor so tuần trước, báo khi đổi |

Chạy trực tiếp không qua Claude cũng được: `python3 bin/doctor.py`, `printf "prompt" | python3 bin/dispatch.py codex --result-json`, v.v.

Các cờ mở rộng của `bin/dispatch.py`:
- `--doctor`: Chạy lệnh `verify_cmd` cho vendor và in trạng thái.
- `--allow-unknown-model`: Cho phép gọi các model không có mặt trong danh sách JSON (catalog advisory).
- `--no-traps`: Ẩn các cảnh báo trap trên stderr.
- `--dump-config`: In cấu hình vendor và thoát.
- `--prompt-file <path>`: Đọc prompt từ file thay vì stdin — **bắt buộc dùng cho prompt dài,
  nhiều dòng, hoặc có dấu tiếng Việt**; `echo "..."` vỡ ở tầng shell.
- `--profile <name>`: Chọn profile cấu hình vendor (vd: `glm-5.3-flash`, `kho`, `claude`).
- `--provider <name>`: Chỉ định provider tường minh (vd: `opencode-go`).
- `--effort <level>`: Chọn mức suy luận reasoning (`low`, `medium`, `high`, `max`...).
- `-f, --file <path>`: Đính kèm file ảnh/PDF cho vision (lặp lại được: `-f a.png -f b.png`).
- `--synthetic-vision`: Khai báo tường minh file đính kèm là dữ liệu tổng hợp / synthetic.
- `--allow-sensitive-vision`: Cờ cho dữ liệu nhạy cảm (mặc định bị chặn fail-closed do chưa có UX consent mỗi lượt).
- `--stream-diagnose`: Chạy vendor ở chế độ stream để bắt output khi timeout (BUG-6).
- `--result-json`: Trả kết quả chuẩn hoá qua JSON (`status`, `served_model`, `exit_code`, `warnings`).

## Vendor — cài & auth
Chạy `/polykit:doctor` bất cứ lúc nào để xem cái nào chưa sẵn sàng + lệnh auth cụ thể. PolyKit hỗ trợ các vendor và adapter: `agy, dsh, grok, codex, gemini, claude, openrouter, opencode, hermes`.

| Vendor | Cách sẵn sàng | Guide |
|---|---|---|
| **Claude** | Đã auth sẵn qua Claude Code (host). | [docs/vendors/claude.md](docs/vendors/claude.md) |
| **Codex** | Cài Codex CLI → `codex login`. Mặc định: `gpt-6.1-sol`, reasoning effort `low`. | [docs/vendors/codex.md](docs/vendors/codex.md) |
| **Gemini** | Cài Gemini CLI → chạy `gemini` rồi `/auth`. Hoặc chỉ cần biến môi trường `GEMINI_API_KEY`. | [docs/vendors/gemini.md](docs/vendors/gemini.md) |
| **Grok** | Cài Grok CLI → `grok` để auth. | [docs/vendors/grok.md](docs/vendors/grok.md) |
| **Agy** | Cài Antigravity CLI → chạy `agy` để auth. Mặc định giữ nguyên: `gemini-3.8-flash-high`. | [docs/vendors/agy.md](docs/vendors/agy.md) |
| **Dsh** (DeepSeek Harness) | Cài Dsh CLI → export `DEEPSEEK_API_KEY=...`. Mặc định: `deepseek-v4-pro`, reasoning effort `high`. | [docs/vendors/dsh.md](docs/vendors/dsh.md) |
| **OpenRouter** | Ghi API key vào file `~/.config/openrouter/key` hoặc export `OPENROUTER_API_KEY`. | [docs/vendors/openrouter.md](docs/vendors/openrouter.md) |
| **OpenCode** (Go adapter) | Adapter Go dùng provider `opencode-go`, chung quota group `opencode-go`. Mặc định `deepseek-v4.1-flash` (high), profile `glm-5.3-flash` (max). *(Hiện sandbox chưa verified → dispatch bị chặn `sandbox_unsupported`)* | [config/vendors.json](config/vendors.json) |
| **Hermes** (Go adapter) | Adapter Go dùng provider `opencode-go`, chung quota group `opencode-go`. Mặc định `deepseek-v4.1-flash` (high), profile `glm-5.3-flash` (max). *(Hiện sandbox chưa verified → dispatch bị chặn `sandbox_unsupported`)* | [config/vendors.json](config/vendors.json) |

## Tuỳ biến JSON (config/vendors.json)
Người dùng có thể thêm vendor mới bằng cách chỉnh sửa JSON schema với các trường:
- `headless`: Lệnh chạy CLI dạng không-cần-người-dùng (ví dụ: `vendor-cli -p '<prompt>'`).
- `model_flag`: Cờ dùng để chỉ định model (ví dụ: `-m` hoặc `--model`).
- `models`: Danh sách các model hỗ trợ (list các string).
- `traps`: Danh sách các cảnh báo, lỗi tiềm ẩn khi dùng vendor (list string).
- `zero_quota_cmds`: Lệnh chạy không tốn token dùng để verify auth (`--doctor`).

## Mac vs Windows
- **doctor / dispatch / failover**: chạy y hệt cả hai (Python stdlib).
- **watcher tự chạy hàng tuần**: Mac dùng `launchd`, Windows dùng `schtasks` — tự chọn theo OS. Linux: chạy watcher thủ công (cron adapter chưa làm).

## Nguyên tắc
- Vendor thiếu/chưa auth/hết quota → **degrade rõ ràng**, không bao giờ crash.
- Claude lane bị **giới hạn** (plan-mode, không tool) theo ToS — không dùng làm worker.
- State (cache) tự sinh; xoá được, tự tạo lại.
- **PII thật (tên/CIF/MST/số dư khách hàng) không rời Claude host** — muốn dispatch phải khử
  định danh trước. Chi tiết: `docs/CHIA-VIEC.md` §PII.
- **Chính sách Model & Routing**:
  - Model `*-contributor`: **Cấm tuyệt đối** trên mọi vendor/provider (nguy cơ train trên data), không cho bypass kể cả với `--allow-unknown-model`.
  - Model `*-free`: **Chỉ cho phép chọn tường minh** (`explicit-only`); cấm tuyệt đối dùng làm default, auto router, hoặc failover.
  - OpenRouter: Chặn các router generic chưa rõ đích (`auto`, `free`, `free-router`, `:free`) và model `:free` (`unresolved destination`).
  - Catalog models: Mang tính chất **khuyến cáo (advisory)** cảnh báo khi model lạ, **không phải whitelist cứng** gây chặn oan model mới.
- **Trạng thái Go Adapters & Vision (CHƯA LIVE TEST)**:
  - Go adapters (`opencode`, `hermes`): Cùng provider `opencode-go`, quota group chung `opencode-go`. Hiện tại **sandbox chưa được kiểm chứng cách ly an toàn** (`no proven confinement`) → dispatch bị chặn fail-closed (`status=blocked`, reason `sandbox_unsupported`). Không nói Go dispatch/vision đang hoạt động.
  - Cổng Vision: Dữ liệu nhạy cảm / sensitive vision mặc định **bị chặn** (`vision_blocked`). Chưa có cơ chế UX consent từ Tuan mỗi lượt thì không mở. Thỏa thuận ZDR (Zero Data Retention) **không thay thế** các cổng kiểm soát an toàn.
  - Mọi đánh dấu hiện tại là **CHƯA LIVE TEST** — điều phối sẽ tự chạy nghiệm thu và ghi báo cáo riêng.
- Docs không phải nguồn sự thật về model/version — `/polykit:doctor` mới là. Số trong docs chỉ
  là snapshot có ghi ngày.
- **"Vendor được gọi" ≠ "vendor phục vụ".** Khi model thật khác model đã yêu cầu (router OR,
  lane `agy`, `gemini auto`...), dispatch ghi dòng `[polykit] served: <model>` ra **stderr**
  (không phải stdout — stdout phải sạch để pipe). Ai redirect stderr đi chỗ khác sẽ không thấy.
  Dùng `--result-json` để đọc field `served_model` bền hơn (không phụ thuộc redirect). Lưu ý:
  độ tin cậy của field này khác nhau theo vendor — xem ghi chú riêng ở `docs/vendors/<vendor>.md`
  (vd. OpenRouter đọc thẳng từ response API = bằng chứng; agy chỉ là slug đã gửi = ý định, agy
  không báo lại model thật đã chạy).

- **Thấy bug thì ghi vào [docs/BUGS.md](docs/BUGS.md)**, kèm lệnh nguyên văn và cái đã ĐO được;
  sửa được trong phiên thì sửa luôn và ghi bằng chứng. Đừng để sổ bug nằm ngoài git.
- **Sửa code ở repo, không sửa trong thư mục plugin đã cài** — bản cài sẽ bị đồng bộ đè.

MIT. Repo: github.com/nightskat/polykit
