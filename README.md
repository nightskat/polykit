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

Ví dụ cờ cho Go adapter (`opencode`, `hermes`) — unsandboxed chỉ với cờ tường minh:
```bash
# qua cổng: cờ --data-class code-nopii, prompt text, không attachment
echo "def add(a, b): return a + b" | python3 bin/dispatch.py opencode --data-class code-nopii --result-json
python3 bin/dispatch.py hermes --data-class code-nopii --model deepseek-v4.1-flash --prompt-file my_code.py --result-json
python3 bin/dispatch.py opencode --data-class code-nopii --model glm-5.3-flash --prompt-file my_code.py --result-json

# bị chặn: thiếu cờ → status=blocked, reason=sandbox_unsupported
echo "..." | python3 bin/dispatch.py opencode --result-json
# bị chặn: attachment/vision trên lane này, kể cả khai báo synthetic → status=blocked, reason=vision_blocked
python3 bin/dispatch.py opencode --data-class code-nopii --synthetic-vision -f a.png --result-json
```
`--data-class` chỉ nhận `code-nopii`. Prompt text còn đi qua `pg-redact check` nếu máy có checker
(không có checker → warning, vẫn chạy text).

Các cờ mở rộng của `bin/dispatch.py`:
- `--doctor`: Chạy lệnh `verify_cmd` cho vendor và in trạng thái.
- `--allow-unknown-model`: Cho phép gọi các model không có mặt trong danh sách JSON (catalog advisory).
- `--no-traps`: Ẩn các cảnh báo trap trên stderr.
- `--dump-config`: In cấu hình vendor và thoát.
- `--data-class <class>`: Khai báo loại dữ liệu cho lane Go unsandboxed (`opencode`, `hermes`). Bắt buộc dùng `code-nopii` (code / dữ liệu không PII); thiếu cờ sẽ bị chặn `sandbox_unsupported`.
- `--prompt-file <path>`: Đọc prompt từ file thay vì stdin — **bắt buộc dùng cho prompt dài,
  nhiều dòng, hoặc có dấu tiếng Việt**; `echo "..."` vỡ ở tầng shell.
- `--profile <name>`: Chọn profile cấu hình vendor (vd: `glm-5.3-flash`, `kho`, `claude`).
- `--provider <name>`: Chỉ định provider tường minh (vd: `opencode-go`).
- `--effort <level>`: Chọn mức suy luận reasoning (`low`, `medium`, `high`, `max`...).
- `-f, --file <path>`: Đính kèm file ảnh/PDF cho vision (lặp lại được: `-f a.png -f b.png`). Trên lane Go unsandboxed (`opencode`/`hermes`): **bị chặn** (`vision_blocked`).
- `--synthetic-vision`: Khai báo tường minh file đính kèm là dữ liệu tổng hợp / synthetic. Trên lane Go unsandboxed: **bị chặn** (`vision_blocked`).
- `--allow-sensitive-vision`: Cờ cho dữ liệu nhạy cảm (mặc định bị chặn fail-closed do trustedUI chưa hỗ trợ xác nhận mỗi lượt). Trên lane Go unsandboxed: **bị chặn** (`vision_blocked`).
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
| **OpenCode** (Go adapter) | Adapter Go dùng provider `opencode-go`, chung quota group `opencode-go`. Mặc định `deepseek-v4.1-flash` (high), profile `glm-5.3-flash` (max). Chạy unsandboxed CHỈ khi có cờ tường minh `--data-class code-nopii` (không cờ → chặn `sandbox_unsupported`). | [config/vendors.json](config/vendors.json) |
| **Hermes** (Go adapter) | Adapter Go dùng provider `opencode-go`, chung quota group `opencode-go`. Mặc định `deepseek-v4.1-flash` (high), profile `glm-5.3-flash` (max). Chạy unsandboxed CHỈ khi có cờ tường minh `--data-class code-nopii` (không cờ → chặn `sandbox_unsupported`). | [config/vendors.json](config/vendors.json) |

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
- **Trạng thái Go Adapters & Cổng dữ liệu unsandboxed** (snapshot 22/10/2026):
  - Go adapters (`opencode`, `hermes`): chạy **unsandboxed CHỈ khi khai báo tường minh `--data-class code-nopii`** (code / dữ liệu không PII). Không có cờ → vẫn chặn fail-closed `reason=sandbox_unsupported` (Plan mục 83), không probe/spawn/network. Không có cờ bool/model/evidence_sandbox nào thay thế được cờ này.
  - Kết quả khi qua cổng: `--result-json` ghi `unsandboxed: true` + `data_class: "code-nopii"`; mọi lượt bị chặn ghi `unsandboxed: false`.
  - Cổng kiểm soát dữ liệu (`bin/lib/go_data_gate.py`), thứ tự kiểm: cờ → attachment/vision → PII:
    - `pg-redact check <prompt tạm>` nếu máy có checker: phát hiện PII / exit≠0 (`pii_detected`), timeout 20s hoặc lỗi (`pii_checker_failed`) → **fail-closed**, chặn trước probe/spawn/network. Không in và không log prompt hay output của checker.
    - Thiếu `pg-redact`: chỉ ghi warning rõ; text vẫn chạy được vì caller đã khai báo `code-nopii`, còn attachment vẫn bị cấm.
    - Attachment & mọi cờ vision synthetic/sensitive (`-f`/`--file`, `--synthetic-vision`, `--allow-sensitive-vision`, xác nhận nhạy cảm) đều **chặn tuyệt đối** (`reason=vision_blocked`), kể cả khi không có file thật.
  - **Đây không phải sandbox**: chưa có cách ly nào được chứng minh (`no proven confinement`), và `pg-redact` chỉ kiểm **prompt** — không bảo đảm workspace sạch. Vendor chạy có tool đọc/ghi workspace, nên lane này chỉ dùng cho code không PII; dữ liệu thật (tên/CIF/MST/số dư) vẫn cấm tuyệt đối.
  - Cổng Vision của dispatch **vẫn đóng**: không có đường dispatch vision, và `--synthetic-vision` không mở lane Go. Ảnh tổng hợp chỉ được thử **trực tiếp ngoài dispatch** (`opencode run ... -f docs/plans/evidence/2026-10-22/vision-synthetic.png`), đọc ra đủ 3 trường (Amount, Date, ID) — bằng chứng `docs/plans/evidence/2026-10-22/live-vision-round2.json`; đây không phải tính năng của dispatch.
  - **Live test 22/10/2026 (vòng 2)** — bằng chứng `docs/plans/evidence/2026-10-22/live-text-round2.json`, `live-deepseek-retry-round2.json`:
    - `opencode` DeepSeek-v4.1-flash high: lượt đầu fail vì vendor `database is locked`, retry trả `LIVE_OK` (13,65s).
    - `opencode --model glm-5.3-flash`: `LIVE_OK` (18,39s). `hermes` default DeepSeek-v4.1-flash: `LIVE_OK` (15,23s).
    - `--model deepseek-v4.1-flash-free` (explicit): vendor trả lỗi `UnknownError: Unexpected server error. Check server logs for details.` — lỗi phía vendor, không phải PolyKit chặn.
    - `--model gemini-4-argon-contributor` → `blocked` `contributor_model_blocked`; không cờ `--data-class` → `blocked` `sandbox_unsupported`; `--allow-sensitive-vision` → `blocked` `vision_blocked`.
    - `served_model`: chưa xác nhận (`null`) ở cả 3 lượt text — CLI subprocess không có trusted envelope.
- Docs không phải nguồn sự thật về model/version — `/polykit:doctor` mới là. Số trong docs chỉ
  là snapshot có ghi ngày.
- **"Vendor được gọi" ≠ "vendor phục vụ" & Bằng chứng xác thực (`served_model`)**:
  - Khi output là plaintext hoặc không có trusted envelope (chạy CLI subprocess như agy, gemini CLI, codex, dsh...), `served_model = None` (`null` trong JSON). Việc ghim model tường minh (`explicit pin` trên argv/CLI) **KHÔNG chứng minh** được model thật đã phục vụ.
  - JSON do assistant (model completion) tự sinh chứa `model` hay `modelVersion` trong câu trả lời **không phải metadata tin cậy**.
  - **Chỉ có** trường `model` trong HTTP response của OpenRouter hoặc `modelVersion` ở top-level response envelope của Gemini API mới là bằng chứng xác thực (`evidence`).
  - Khi có evidence xác nhận model thật khác model đã yêu cầu, dispatch ghi dòng `[polykit] served: <model>` ra **stderr** (không in ra stdout để pipeline luôn sạch). Dùng `--result-json` để đọc field `served_model` chuẩn hoá.

- **Thấy bug thì ghi vào [docs/BUGS.md](docs/BUGS.md)**, kèm lệnh nguyên văn và cái đã ĐO được;
  sửa được trong phiên thì sửa luôn và ghi bằng chứng. Đừng để sổ bug nằm ngoài git.
- **Sửa code ở repo, không sửa trong thư mục plugin đã cài** — bản cài sẽ bị đồng bộ đè.

MIT. Repo: github.com/nightskat/polykit
