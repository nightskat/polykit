# PLAN — thêm Hermes/OpenCode và bảo trì default vendor (22/10/2026)

Chỉ lập kế hoạch; phiên này không sửa code/config, không chạy task suy luận hay gửi hồ sơ ra vendor.
Đã đọc `CLAUDE.md`, `SPEC.md`, `docs/BUGS.md`; đối chiếu BUG catalog Codex tại commit `7596d26`.
Giữ Python-first, config ≠ state, graceful degradation, Result JSON và Claude bounded theo P1–P5.

## 1. Bằng chứng tại máy và default đề xuất

Lệnh kiểm tra dưới đây là lệnh tái kiểm; catalog/help không chứng minh một lượt suy luận đã thành công.
Các default dưới đây là đề xuất cho IMPLEMENT; chưa kiểm catalog/effort thì chưa áp dụng thay đổi.

| Vendor | Model + effort đề xuất | Lệnh kiểm chứng và kết quả phiên này |
|---|---|---|
| codex | `gpt-6.1-sol` + `low` | `codex debug models </dev/null`: exit 0, có slug và default reasoning `low`; không có `gpt-5.5`. Builder dùng `-c model_reasoning_effort=low`. |
| agy | Giữ `gemini-3.8-flash-high` (Tuan chốt) | ĐÃ KIỂM: Claude chạy `agy models` ngoài sandbox; đã đọc `evidence/2026-10-22/agy-models.txt` tại thư mục bằng chứng bên dưới. Có Gemini 4 Argon/3.8 Flash, Opus/Sonnet 5.5 mỗi loại low/medium/high và `gpt-oss-120b-medium`; ghim slug, không truyền effort lần hai. |
| dsh | Giữ `deepseek-v4-pro` + `high`: tau 76,96% ≈ Flash 76,80%, chưa đủ đổi default | Giữ default thực thi `DSH_DEFAULT_MODEL`, đồng bộ JSON đang ghi flash. `dsh --profile headless --dump-config`: EPERM khi ghi profile; CHƯA xác minh effort tại máy. |
| grok | Giữ `grok-4.6` + đề xuất `low` có điều kiện; CSV thiếu 4.7 nên chưa đề xuất nâng | `grok models </dev/null`: exit 0, có 4.6/4.5, CLI default 4.5; stderr báo settings fetch failed. `grok --help` có `--reasoning-effort`; chưa xác minh 4.6 nhận low, không công bố đã ghim thành công. |
| gemini | Tạm `auto`; đề xuất `gemini-3.8-flash` nếu tài khoản hỗ trợ: GPQA 95,64%, rẻ hơn Argon; effort CHƯA KIỂM | `gemini --help </dev/null` không có lệnh list model/effort; mở `gemini`, dùng `/model` để kiểm danh sách thật. Chưa mở TUI; giữ `models=null`/CHUA_KIEM đến khi xác minh tài khoản và lane thực thi. |
| claude | Đề xuất `claude-sonnet-5-5` + `medium`, chờ catalog CLI: tau 78,67% ≈ Opus 5 78,79%, cost $0,15990 so $0,48460; hiện giữ Opus 5 low | Không dùng `claude models` vì bị hiểu là prompt. Tái kiểm bằng `claude --help </dev/null`, rồi `/model` trong TUI; phiên này help lần đầu timeout 12s, retry exit 0 nhưng rỗng, CHƯA xác minh catalog. Giữ đủ cờ bounded hiện có; catalog agy không chứng minh catalog Claude CLI. |

agy chỉ thêm lane phụ, chọn tường minh: `kho` = `gemini-4-argon-high` (tau 78,67% > Flash 71,28%, API đắt hơn); `claude` = `claude-sonnet-5-5-medium` (tau ngang Argon, rẻ hơn).
`claude-opus` = `claude-opus-5-5-low` dành đối chứng khác model, không mặc định mạnh hơn Sonnet; `oss` = `gpt-oss-120b-medium` cho việc nhẹ, tau/GPQA thấp hơn.
DSH không có lệnh list trong launcher help: kiểm catalog bằng API `/models`, không bịa `dsh models`.
Lệnh tái kiểm: `curl --fail --silent --show-error -H "Authorization: Bearer $DEEPSEEK_API_KEY" https://api.deepseek.com/models`.
Phiên này chưa gọi API vì env không có key; không in key/dump config thô vào evidence. Để kiểm effort DSH: tạo patch trong tmp, có `agent-default-model.config.{provider: deepseek-official, model: deepseek-v4-pro}`
và `llm-deepseek.config.reasoningEffort: high`; chạy `dsh --profile headless --patch <patch.yml> --dump-config`, chỉ trích model/effort.
Grok: chỉ kích hoạt `--reasoning-effort low` sau smoke tổng hợp chứng minh hỗ trợ; không âm thầm bỏ effort nếu bị từ chối. Gemini: chưa đổi config sang ứng viên; tài liệu `/model` không chứng minh quyền truy cập của tài khoản này.

## Bằng chứng benchmark

CSV OpenRouter ngày 22/10/2026: 2.199 dòng; nguồn [Benchmarks](https://openrouter.ai/benchmarks), [Rankings](https://openrouter.ai/rankings).
Python `csv.DictReader`: lọc đúng `model_slug` + benchmark; chọn `auto-routing`, riêng Argon chỉ có Google; nếu trùng lấy `last_run_timestamp` mới nhất.
Mỗi ô = accuracy % / USD mỗi task (5 số lẻ); giữ accuracy và cost cùng dòng, không trộn provider hay chọn điểm cao nhất.
CSV chỉ có [tau2-bench Airline](https://openrouter.ai/benchmarks/tau2-bench-airline) (`tau_bench_verified_airline`, agentic) và [GPQA Diamond](https://openrouter.ai/benchmarks/gpqa-diamond) (`gpqa_diamond`, suy luận); không có bench coding khác, vision hay OCR (đã kiểm toàn bộ 2.199 dòng).

| Model API (tiền tố chỉ nhà cung cấp model) | tau2-bench Airline | GPQA Diamond |
|---|---|---|
| `deepseek/deepseek-v4.1-flash` | 76.80% / $0.03498 | 89.09% / $0.02464 |
| `deepseek/deepseek-v4-pro` | 76.96% / $0.04528 | 86.55% / $0.03886 |
| `z-ai/glm-5.3` | 77.52% / $0.06097 | 85.23% / $0.10543 |
| `z-ai/glm-5.3-flash` | 75.90% / $0.00737 | 84.62% / $0.01534 |
| `xiaomi/mimo-v2.6-flash` | 78.67% / $0.01539 | 73.93% / $0.01632 |
| `qwen/qwen3.8-2.4t-a95b` | 75.62% / $0.19364 | 87.08% / $0.08650 |
| `qwen/qwen3.8-27b` | 77.92% / $0.07310 | 81.84% / $0.03440 |
| `qwen/qwen3.8-flash` | 71.33% / $0.01665 | 88.55% / $0.02146 |
| `moonshotai/kimi-k3` | 72.80% / $0.29079 | 91.93% / $0.13230 |
| `minimax/minimax-m3` | 74.78% / $0.02390 | 90.46% / $0.03434 |
| `openai/gpt-6.1-sol` | 70.00% / $0.10128 | 94.44% / $0.02137 |
| `openai/gpt-6-sol` | 69.33% / $0.13000 | 91.92% / $0.02528 |
| `openai/gpt-6-luna` | 67.33% / $0.00929 | 89.85% / $0.00344 |
| `openai/gpt-5.6-sol` | 74.67% / $0.18399 | 92.09% / $0.06044 |
| `x-ai/grok-4.6` | 75.33% / $0.33087 | 92.85% / $0.12327 |
| `google/gemini-3.8-flash` | 71.28% / $0.21022 | 95.64% / $0.06823 |
| `google/gemini-4-argon` | 78.67% / $0.49829 | 96.46% / $0.09468 |
| `anthropic/claude-opus-5.5` | 75.50% / $0.33917 | 90.45% / $0.05431 |
| `anthropic/claude-sonnet-5.5` | 78.67% / $0.15990 | 92.37% / $0.02507 |
| `openai/gpt-oss-120b` | 64.67% / $0.01436 | 72.31% / $0.00577 |
| `anthropic/claude-opus-5` | 78.79% / $0.48460 | 87.71% / $0.13007 |
| `x-ai/grok-4.7`, `qwen/qwen3.8-max` | Không có trong CSV | Không có trong CSV |

Không tự đồng nhất Qwen `2.4t-a95b` với Go `qwen3.8-max`; `qwen3.8-27b` không nằm trong catalog Go đã cung cấp.
Bench OpenRouter đo qua API; effort/routing/harness có thể khác CLI và gói Go; cost/task không phải giá thuê bao. Có mẫu chỉ 1 run, chưa đủ suy ra khác biệt có ý nghĩa thống kê; Rankings không thay điểm bench.

## 2. Hai vendor mới và hai hồ sơ OpenCode Go

- `opencode` và `hermes` là hai adapter/harness riêng; cùng `provider=opencode-go`, `quota_group=opencode-go`.
- Thay quy tắc `_luat` đang loại OpenCode khỏi registry: cho phép adapter riêng vì người dùng yêu cầu; không coi là hai túi quota.
- Cả hai giữ default `deepseek-v4.1-flash` + `high`: GPQA 89,09% hơn hai GLM và MiMo; tau 76,80%. Cân nhắc lại `glm-5.3-flash` + `max`: chỉ là hồ sơ chọn tường minh, không gọi là tiết kiệm hay mạnh hơn cho việc khó.
- Config giữ model slug trần, provider/effort riêng; pin một lần qua resolver chung cho CLI và lời gọi thư viện.
- Khi chọn GLM Flash mà không ghi effort, lấy `max` từ hồ sơ; mapping effort vẫn cần smoke. Chưa thay bằng GLM thường: tau +1,62 điểm % nhưng cost ≈8,3 lần, GPQA chỉ +0,61 điểm %.
- Đề xuất thử `mimo-v2.6-flash` cho tool/agentic (tau 78,67%, $0,01539; GPQA chỉ 73,93%); Qwen Flash/Max chưa đủ bằng chứng thay default. Chỉ duyệt model có trong catalog Go người dùng cung cấp, chặn cứng `*-contributor`; `*-free` không làm default, cho chọn tường minh (Tuan chốt 22/10).
- Theo `evidence/2026-10-22/go-page.md`, Go ≈34.670 req/5h DeepSeek Flash, 6.320 GLM Flash, 30.100 MiMo Flash; GLM ít lượt hơn DeepSeek ≈5,5 lần. Đây là ước tính, không bảo đảm số lượt thực tế; cost API không suy ra quota Go.
- Trần Go: cửa sổ 5h = 20% hạn mức tháng, tuần = 50%, tháng = 100%; failover phải đọc cả ba cửa sổ, không đổi harness để né trần chung.
- DeepSeek không train + ZDR hiện chỉ tới **31/10/2026**, gia hạn từng tháng: watcher/doctor cảnh báo sắp hết, hết hạn hoặc chưa xác minh gia hạn; không coi 0 ngày lưu là vĩnh viễn.
- OpenCode binary: `Path.home() / '.opencode/bin/opencode'`, expand thành absolute path; không phụ thuộc alias/PATH.
- Argv: `opencode run --model opencode-go/<m> --variant <effort> <PROMPT>`; `stdin=subprocess.DEVNULL`, không dùng shell.
- `~/.opencode/bin/opencode run --help </dev/null` exit 0: xác nhận `--model` và `--variant` tại bản cài.
- Lần gọi `models opencode-go` trước bị lỗi log; nay đã đọc metadata thật `evidence/2026-10-22/opencode-go-verbose.txt`, có hai slug và capabilities; chưa chứng minh effort/dispatch thành công.
- Hermes argv dự kiến: `hermes -z <PROMPT> --provider opencode-go -m <m> --reasoning <effort>`, stdin DEVNULL.
- ĐÃ KIỂM: theo kết quả Claude chạy `hermes --help` ngoài sandbox, exit 0, có `-z PROMPT`, `-m`, `--provider`, `--reasoning`; khớp parser Context7. Help chưa chứng minh dispatch/effort thành công.
- Không tự sửa lock/quyền hay cài lại CLI; nếu cờ bản cài khác tài liệu, báo unsupported, không đoán cờ thay thế.
- Headless không đồng nghĩa sandbox: Hermes oneshot tự bypass approval và vẫn tải tools/memory/rules; phải kiểm tool policy.
- Chỉ bật dispatch khi chứng minh được giới hạn `read-only`/`workspace-write`; không hỗ trợ thì trả blocked rõ lý do.
- Giữ cwd theo `--cd`; cwd sạch không đủ cách ly ổ đĩa. Không bật auto-approve hay nạp session cũ ngầm.
- Timeout, stderr tail, output rỗng/exit 0 giả và requested/served_model theo contract hiện có; không tự nhận served nếu không có bằng chứng.

## 3. Chốt chặn dữ liệu và catalog

- Policy chung: chặn cứng `*-contributor` vì có train. `*-free` không phải default vì khuyến mãi có hạn, 200 req/ngày; **Tuan đã quyết 22/10: CHO chọn tường minh** (`--model ...-free`), không bao giờ làm default, auto hay failover; test phải chứng minh.
- Chuẩn hóa provider/model, khoảng trắng, hoa thường và selector variant trước khi kiểm; malformed/ambiguous selector phải bị chặn.
- Chặn trước probe/spawn/network, sau resolve alias/default/profile; áp dụng CLI và `run_vendor`, builder/API entrypoint.
- Không cho `--allow-unknown-model`, config/state bị sửa, watcher hay failover vượt chốt; trả blocked + reason riêng + JSON đầy đủ.
- Với hai adapter Go, chỉ cho provider `opencode-go` và hai hồ sơ đã duyệt; không cho router/auto đổi sang contributor hay free; free chỉ chạy khi người gọi ghi tường minh.
- Rà `:free`/free-router OpenRouter riêng: không suy chính sách Go cho mọi provider; chưa rõ model đích/train/lưu trữ thì chặn, không fallback vào nguồn chưa duyệt.
- Catalog advisory khác policy cấm: model hợp lệ nhưng chưa có trong catalog chỉ cảnh báo; không cần bypass để chạy Codex mới.
- Bỏ whitelist hard-code `models` trong JSON (giữ `null` tương thích schema 3); config chỉ giữ default/profile/policy.
- Watcher lấy catalog từ CLI/API đã kiểm, parser riêng cho JSON Codex/bảng CLI; không dùng parser slug thô cho toàn bộ JSON.
- State có nguồn catalog, thời điểm, lỗi và độ mới; lỗi mạng giữ last-known-good, đánh dấu stale, không coi là model bị xóa.
- Watcher cảnh báo drift nhưng không tự đổi default/effort đã duyệt; catalog chứa model cấm không bao giờ trở thành route hợp lệ.

## Lane VISION

Bổ trợ PDF scan mà `vnocr` (OCR cục bộ của Tuan) xử lý chưa tốt; không thay vnocr. Giữ bản gốc, số trang và đối chiếu trường quyết định bằng ảnh nguồn.
Dispatch dự kiến nhận danh sách đính kèm ảnh/PDF, kiểm MIME + `capabilities.input.image/pdf` của model đã resolve; cờ CLI có mặt chưa chứng minh model nhận hay đọc đúng file.
Đã chạy help tại máy ngày 22/10 (stdin DEVNULL, timeout 18s); chỉ các cờ sau được xác nhận:

| Adapter | Bằng chứng đính kèm và giới hạn |
|---|---|
| OpenCode | `opencode run --help` exit 0: `-f/--file` (array); `--attach` là nối server, không phải đính kèm file. Cần smoke ảnh/PDF tổng hợp. |
| Hermes | `hermes --help` ngoài sandbox exit 0 (Claude chạy); trong sandbox Codex exit 1 do `.install.lock`. Đính kèm **CHƯA KIỂM**, help cũ chỉ xác nhận provider/model/effort. |
| Codex | `codex --help` exit 0: `-i/--image <FILE>...` cho ảnh; PDF trực tiếp **CHƯA KIỂM**; tái kiểm `codex exec --help` trước builder headless. |
| agy | `agy --help` exit 0, không thấy cờ đính kèm; `-i` là prompt interactive. Truyền ảnh/PDF và schema stream-json **CHƯA KIỂM**. |
| Gemini | `gemini --help` exit 0 không mô tả `@file`; cơ chế `@file` cho ảnh/PDF **CHƯA KIỂM**, chưa mở adapter vision. |
| Grok | `grok --help` exit 0 có `--prompt-json` (content blocks), `--prompt-file` (prompt văn bản); schema ảnh/PDF **CHƯA KIỂM**, không coi prompt-file là ảnh. |

Metadata Go thật (khác khả năng vận chuyển file của harness):

| Model | input.image / input.pdf | Train / lưu trữ theo evidence/2026-10-22/go-page.md | Đề xuất |
|---|---|---|---|
| `deepseek-v4.1-flash` | true / false | Không / 0 ngày tới 31/10/2026 | Default vision tạm thời, phải còn xác minh ZDR |
| `glm-5.3-flash` | true / true | Không / 0 ngày | Dự phòng, nhận PDF trực tiếp nếu smoke đạt; quota thấp |
| `mimo-v2.6-flash` | true / false | Không / 0 ngày | Ứng viên bench; chưa tự thay dự phòng |

DeepSeek PDF phải **tách từng trang thành ảnh trước** bằng `pdftoppm`; `vnocr --contact-sheet` hỗ trợ kiểm kê/chọn trang, không dùng ảnh contact sheet thu nhỏ để đọc số. Không gửi PDF trực tiếp khi `pdf=false`.
GLM 5.3 thường và DeepSeek V4 Pro đều image/pdf=false; không chọn theo tên họ model. Haiku/Luna/Grok có image/pdf=true nhưng lưu 30 ngày nên không ưu tiên; contributor luôn bị chặn.
CSV chỉ có tau/GPQA, không có bench vision/OCR: lựa chọn trên dựa capabilities + privacy + quota, **chưa có bằng chứng chất lượng OCR**. Cần bench nhỏ trên vài trang tổng hợp có đáp án biết trước, mô phỏng lỗi vnocr; đo đúng/sai số tiền, ngày, định danh, ô bảng và sót trường; không tin điểm tự tin, không dùng tau/GPQA thay OCR.
**PII / QUAN SÁT-3:** scan ngân hàng chứa PII dạng ảnh; pg-redact bôi text không bôi được ảnh. Dữ liệu thật bị chặn mặc định trước đọc/upload/probe/spawn/network; cần cờ tường minh dự kiến `--allow-sensitive-vision` **và xác nhận của Tuan mỗi lượt** gắn bộ file/model/provider, không lưu đồng ý lâu dài hoặc kế thừa qua retry/failover. Không nhận đủ xác nhận thì blocked; smoke chỉ ảnh/PDF tổng hợp. Không-train/ZDR không thay cổng này.

## 4. File sẽ sửa khi IMPLEMENT

- `config/vendors.json`: hai adapter, provider/quota group/hồ sơ/default effort, vision default/dự phòng + chính sách free chờ quyết; đồng bộ defaults cũ và bỏ whitelist lỗi thời.
- `bin/lib/vendor_config.py`: accessor/resolver model+effort+profile dùng chung, kiểm schema và tương thích config hiện hành.
- Mới `bin/lib/model_policy.py`: kiểm model/provider độc lập catalog; mới `bin/lib/vision.py`: kiểm file/MIME/capabilities, tách PDF, cổng PII và xác nhận mỗi lượt trước I/O ra vendor.
- `bin/dispatch.py`, `bin/lib/dispatch_core.py`, `bin/lib/dispatcher.py`: resolve/guard, builder riêng, DEVNULL, effort, cwd, sandbox, phân loại kết quả; thêm attachments/cờ sensitive, nối cổng vision cho CLI/lib/API, chưa hỗ trợ thì blocked.
- `bin/lib/vendors.py`, `bin/doctor.py`: detect đường dẫn, auth/catalog riêng và probe timeout; CLI tồn tại/catalog có model không đủ suy ra ready.
- `bin/lib/states.py`, `bin/lib/state_store.py`: metadata probe/catalog/capabilities + nguồn/ngày hết hạn ZDR; nếu đổi schema state thì bump version và regenerate cache.
- `bin/failover.py`, `bin/lib/quota.py`, `bin/lib/quota_error.py`, `bin/lib/doctor_quota.py`: cap fixtures 5h/tuần/tháng, gợi ý theo quota group và modality/privacy; không vượt xác nhận vision.
- `bin/lib/evidence.py`: metadata quota group tối thiểu nếu cần; không ghi prompt/key, không tự đặt reset TTL Go chưa biết.
- `bin/watcher.py`, `bin/lib/watcher.py`: refresh catalog, lọc route cấm, last-known-good, diff/version/alert một lần và lock; cùng doctor cảnh báo hạn ZDR 31/10 và trạng thái gia hạn.
- `README.md`, `commands/{dispatch,doctor,failover,watcher}.md`, `docs/BUGS.md`: hướng dẫn và bằng chứng sau triển khai; repo hiện không có thư mục `skills/`.
- Giữ thay đổi có sẵn ở `docs/vendors/SNAPSHOT.md`; chỉ refresh snapshot có chủ đích trong phiên triển khai.

## 5. Test bổ sung trong bộ tests/

- Mới `tests/test_model_policy.py`: contributor luôn chặn; free không default, lựa chọn chờ Tuan; bare/provider/variant/case/alias, config/cache xấu, unknown bypass.
- Test spy chứng minh model cấm gọi qua CLI/lib/builder/API không probe/spawn/network; model hợp lệ qua được.
- Mới `tests/test_opencode_hermes.py`: hai vendor × hai hồ sơ, argv/effort/provider/absolute binary/DEVNULL, prompt Việt đa dòng có quote.
- Mở rộng `test_dispatch_builders.py`, `test_dispatch_v2.py`, `test_dispatch_guards.py`, `test_served_model.py`: auto/override, model lạ advisory, stderr/output rỗng/timeout/JSON; bỏ assertion cố định sáu vendor.
- `test_detect_io.py`, `test_doctor_matrix.py`, `test_state_machine.py`: thiếu binary/auth, lock lỗi, transport timeout, catalog rỗng, stale path re-detect một lần.
- `test_bug13_auth_probe_giu_stderr.py`, `test_bug15_auth_probe_timeout_khong_mat_luot.py`: doctor/dispatch dùng chung cơ sở probe, giữ nguyên nguyên nhân và timestamp.
- `test_failover_routing.py`, `test_quota_signal.py`, `test_quota_error.py`, `test_bug4_doctor_doc_quota_that.py`: cap Go không gợi ý harness cùng quota; lỗi lạ không ping; model cấm không thành fallback.
- `test_watcher_diff.py`, `test_watcher_run.py`: model thêm/xóa/effort drift, offline giữ catalog, stale metadata, lock, notify fail retry, alert một lần.
- Mới `tests/test_vision.py`: argv nhiều ảnh/path có khoảng trắng, MIME sai/file thiếu, capabilities thiếu hoặc image/pdf=false, DeepSeek PDF→ảnh đúng thứ tự; không dùng contact sheet làm OCR; adapter CHƯA KIỂM phải blocked.
- Spy PII: thiếu cờ hoặc thiếu xác nhận đúng lượt/file/model thì không upload/probe/spawn/network; retry/failover đổi đích phải xác nhận mới; pg-redact text không mở ảnh; không log nội dung/PII.
- Fixtures quota ba cửa sổ + ZDR trước/đúng/sau 31/10, chưa xác minh gia hạn; vision failover chỉ chọn modality/privacy hợp lệ, không chạy sang harness cùng trần.
- Thêm fixtures help/catalog/cap đã loại secret; giữ `tests/conftest.py` cách ly state/log và negative tests `test_tos_boundary.py`.

## 6. Thứ tự triển khai, nghiệm thu và rủi ro

1. Ghi baseline; kế thừa agy catalog/Hermes help đã kiểm, tái kiểm các mục còn chặn và mapping effort/tool policy; không suy luận từ tên model.
2. Làm policy cấm + negative tests trước, rồi resolver/default/catalog advisory để sửa BUG commit `7596d26`.
3. Thêm config/registry/builder và dispatch hai adapter; chứng minh sandbox rồi mới smoke prompt tổng hợp ở workspace cách ly.
4. Đồng bộ doctor/cache/probe (BUG-14): timestamp/cơ sở ready, auth_unverified khác transport; giữ hành vi BUG-15 cho vendor cũ.
5. Tích hợp failover chung quota, watcher catalog; giữ recommendation-không-ép, không tự chuyển hoặc retry task ghi file; kiểm ba cửa sổ Go và cảnh báo hạn ZDR.
6. Triển khai vision sau cổng PII: tái kiểm help còn thiếu, file transport/MIME/capabilities và PDF→ảnh; adapter chưa chứng minh hỗ trợ phải blocked. Chạy test mục tiêu rồi `python3 -m pytest tests/ -q`; mock runner/notifier/network, không ghi log thật hay gửi Telegram.
7. Smoke bốn tổ hợp vendor/hồ sơ với prompt vô hại; kiểm output/effort và lỗi thực, không chỉ exit 0; bench vision nhỏ có đáp án, chấm đúng/sai số; kiểm chặn dữ liệu thật và xác nhận mỗi lượt; cập nhật docs theo bằng chứng.

QUAN SÁT-3 còn mở: thêm vendor mở thêm biên gửi dữ liệu; model paid không thay thế cổng PII. Không tuyên bố đã sửa PII gate; smoke chỉ dữ liệu tổng hợp. Lane PGBank chưa bật cho vendor mới khi cổng kiểm chưa thi hành được.
Rủi ro chính: CLI đổi cờ (OpenCode upstream đã đổi variant), quyền lock/log, catalog không bằng auth, effort bị bỏ qua, tools đọc ngoài cwd.
Rollback: revert commit triển khai/config, regenerate cache; giữ evidence và defaults đã duyệt, không sửa credential hay bản plugin cài ngoài repo.

Bằng chứng cục bộ: `/private/tmp/claude-501/-Users-nightskat/39707775-2456-4cff-ace4-e0e977f48184/scratchpad/{bench.csv,agy-models.txt,go-page.md,opencode-go-verbose.txt}`; Hermes help theo báo cáo Claude do Tuan cung cấp.
Nguồn đối chiếu Context7: [OpenCode CLI/file](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/cli/cmd/run.ts), [Hermes parser](https://github.com/nousresearch/hermes-agent/blob/main/hermes_cli/_parser.py), [Gemini /model](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/model.md).
