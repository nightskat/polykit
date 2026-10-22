# REVIEW-GROK 2026-10-22

Reviewer: Grok-4.7, adversarial, chỉ đọc repo + probe mocked. Không sửa code sản phẩm, không commit, không vendor live, không Telegram, không network.
Base: 7596d26..HEAD (6e1f638). Acceptance: docs/plans/2026-10-22-them-hermes-opencode.md và BRIEF-SOL.md.
Probe: /Users/nightskat/.hermes/cache/scratch/polykit-grok-probe.py bằng ~/.pyenv/versions/3.11.8/bin/python. Không chạy full pytest.

Không tuyên bố acceptance xong. Go dispatch/vision chưa operational (đúng hướng an toàn, không phải live-complete).

## Đã giữ (tested, không phải finding)

- contributor bị chặn ở check_model_policy kể cả allow_unknown=True và ModelSelector giả is_contributor=False. run_vendor("opencode", model=...-contributor) trả blocked, detector=0, runner=0.
- *-free bị chặn khi source auto/failover/default và khi alias/profile trỏ tới free hoặc contributor. Explicit *-free trên Go được phép — đúng chốt Tuan, không phải bypass.
- OpenRouter org/model không mất namespace. or_dispatch("meta-llama/llama-3-8b-instruct") gửi body model="meta-llama/llama-3-8b-instruct". :free explicit bị openrouter_free_blocked và không gọi opener.
- Catalog lạ là warn, không block. Parser Codex live (vendors.parse_codex_models) lấy slug, không lấy name hiển thị; shape lạ trả [] trên đường watcher, không bịa slug.
- Sensitive vision: cờ allow + SingleTurnConfirmation(is_trusted_ui=True) khớp file/model/provider vẫn blocked, Path.open=0. Retry/failover không kế thừa (nhánh is_valid_for trước I/O). CLI/run_vendor truyền adapter=vendor và không truyền verified_adapters nên adapter chưa verified bị chặn trước open.
- build_opencode_cmd / build_hermes_cmd raise sandbox_unsupported. run_vendor("OpenCode") không spawn (unknown_vendor, runner=0). README/commands nói chưa confinement — khớp code.
- Quota 3 cửa sổ: weekly capped dù 5h/month ok thì is_capped. Thiếu cửa sổ thì unknown, không healthy. Failover không gợi ý hermes khi nguồn là opencode (cùng quota_group). auto_dispatch=False.
- LKG: snapshot có error thì giữ model cũ và stale=True. ZDR sau 2026-10-31 vẫn expired kể cả renewal_verified=True / permanent=True nếu expiry giữ 2026-10-31. Watcher mặc định renewal_verified=False thì should_alert.

## Findings

### 1. High — caller tự chứng nhận adapter vision, hoặc bỏ trống adapter, rồi file bị đọc

Path: bin/lib/vision.py:286 (adapter rỗng thì return), :288 (verified_adapters do caller truyền đè frozenset rỗng), :378, :520 (prepare_vision_input mặc định adapter="").
Test khóa lỗ: tests/test_vision.py:564-575 và :599-608 (không truyền adapter vẫn coi là qua gate).

Reproducer (tested, Path.open spy):
- check_vision_gate(files=[png], model="deepseek-v4.1-flash", adapter="opencode", is_synthetic=True, verified_adapters={"opencode"}) trả 1 attachment và mở file rb, trong khi VERIFIED_VISION_ADAPTERS là frozenset().
- prepare_vision_input(files=[png], model="glm-5.3-flash", is_synthetic=True) cũng mở file rb. Adapter mặc định "" nên verify_adapter bỏ qua.

Tác hại: invariant "adapter chưa verified thì blocked, module không tự bật" không giữ trên API public. Script hoặc caller sau này dùng prepare_vision_input sẽ đọc file (và với PDF + model pdf=false sẽ gọi pdftoppm) dù harness chưa được chứng minh. Cờ is_synthetic là do caller tự đặt, không chứng minh file là tổng hợp. Đường CLI/run_vendor hiện không truyền verified_adapters nên chưa bị lỗ này — lỗ nằm ở API.

Sửa tối thiểu: bỏ tham số verified_adapters khỏi API public; adapter rỗng phải raise VisionBlockedError; chỉ so với hằng VERIFIED_VISION_ADAPTERS. Xóa test "explicitly allowed" cho tới khi có evidence confinement được commit, không phải một set do caller đưa vào.

### 2. High — convert_pdf_to_images spawn pdftoppm không qua cổng

Path: bin/lib/vision.py:441-487. Hàm public, không gọi check_vision_gate, không xem synthetic/allow/confirmation.

Reproducer (tested): convert_pdf_to_images(pdf, out, pdftoppm_bin=fake) với PDF bất kỳ. Fake binary được exec (marker file được ghi) trước khi hàm fail vì không có trang. Không có consent, không có workspace check.

Tác hại: mọi caller có thể tách PDF thật (PII ảnh) thành ảnh và gọi subprocess, đúng thứ plan cấm "trước mọi file I/O/probe/subprocess". Không-train/ZDR không thay cổng này.

Sửa tối thiểu: hàm không public, hoặc bắt buộc nhận kết quả đã qua check_vision_gate (attachment đã validate + synthetic) và từ chối path lạ. Không nhận pdftoppm_bin trỏ ra ngoài sau khi đã bỏ gate.

### 3. High — served_model bịa từ slug đã gửi

Path: bin/lib/dispatcher.py:762-766 (agy), :811-814 (dsh). Cùng lớp, code-confirmed không probe riêng: :1159-1171 (gemini lane 1 ghi agy:{tier}), :1197-1221 (lane 2 ghi cli_model, auto thì hardcode gemini-3.5-flash), :1254-1282 (lane 3 ghi api_model đã nhét vào URL).
Test khóa lỗ: tests/test_agy_vendor.py (served == slug đã gửi), tests/test_policy_entrypoints.py khoảng assert served_model == AGY_DEFAULT_MODEL.

Reproducer (tested): run_vendor("agy", ..., model="gemini-3.8-flash-high", runner trả stdout "hello" và không có field model). Kết quả status=ok, served_model="gemini-3.8-flash-high", warning tự nhận đó là intent.

Tác hại: Result JSON và evidence nói model đã chạy trong khi CLI không báo. Quota, chi phí, và đối soát served≠requested bị sai. Lane gemini auto còn điền một slug không lấy từ response — plan cấm bịa slug Gemini.

Sửa tối thiểu: served_model=None khi vendor không trả model thực. Giữ slug đã gửi ở field requested/model. Warning được phép nói "không xác nhận được". Sửa test đang assert served == intent.

### 4. Medium — helper Go trả argv chạy được, né sandbox_unsupported

Path: bin/lib/dispatch_core.py:490-526 (_build_opencode_argv), :529-562 (_build_hermes_argv). Public build_opencode_cmd/build_hermes_cmd thì raise. Không thấy bin/ gọi helper.

Reproducer (tested): _build_opencode_argv("deepseek-v4.1-flash", prompt) trả list argv tuyệt đối ~/.opencode/bin/opencode, --model opencode-go/..., --variant high, không raise. Hermes helper cùng cấu trúc (code-confirmed, chưa gọi trong probe).

Tác hại: import helper là đường spawn Go không qua chốt confinement. Plan nói caller không được bật bypass. Tính năng vẫn chưa operational — helper không làm nó thành live.

Sửa tối thiểu: helper cũng raise sandbox_unsupported cho tới khi GO_SANDBOX_CONFINED có evidence trong repo. Test hình dạng argv chỉ được chạy sau chốt đó, không được là đường production.

### 5. Medium — failover nhận is_vision/is_sensitive rồi bỏ qua

Path: bin/failover.py:22-34 (chữ ký + docstring), thân hàm không đọc hai cờ; :136 vẫn append. handle_signal truyền cờ xuống nhưng auto_dispatch luôn False.

Reproducer (tested): filter_failover_candidates([hermes paid, codex gpt-6.1-sol, opencode free, contributor], vendor_hint="opencode", is_vision=True, is_sensitive=True) giữ codex. handle_signal cùng cờ, windows 5h remaining=0, ping "Gợi ý: codex" dù task vision+sensitive. Free, contributor, và hermes cùng quota_group bị loại — phần đó đúng.

Tác hại: plan yêu cầu gợi ý vision chỉ model đúng modality/privacy và không vượt xác nhận mỗi lượt. Cờ chết nên ping vẫn chỉ một lane khác cho scan nhạy cảm. Chưa tự dispatch, nên chưa gửi file; người làm theo gợi ý thì gửi.

Sửa tối thiểu: is_sensitive hoặc is_vision thì recommended_candidates=[] và message nói cần xác nhận mới, không gợi ý lane. Không kế thừa confirmation.

### 6. Medium — doctor tin expiry trong config, nuốt ngày 31/10

Path: bin/doctor.py:31 (docstring "Config expiry không được âm thầm gia hạn"), :43-45 (lấy zdr["expiry"] nguyên, không kẹp 2026-10-31). Cờ permanent không được đọc.

Reproducer (tested): check_zdr_expiry({"expiry": "2027-12-31", "renewal_verified": True}, now="2026-11-01") ra status=expiring_soon, days_left=425, không còn chữ hết hạn. Cùng now với expiry 2026-10-31 thì expired — config đang commit là ngày đúng, nên lỗ chưa nổ trên file hiện tại.

Tác hại: sửa một field JSON (hoặc caller truyền zdr) biến "đã hết hạn sau 31/10" thành "còn hạn". Trái plan: ZDR không vĩnh viễn, không gia hạn âm thầm. Watcher.check_deepseek_zdr mặc định vẫn dùng 2026-10-31; lỗ này là doctor.

Sửa tối thiểu: kẹp expiry về min(config, 2026-10-31) hoặc từ chối expiry muộn hơn ngày đã chốt; permanent=True không đổi trạng thái. renewal_verified không được làm mất cảnh báo sau ngày kẹp.

### 7. Medium — builder auto kiểm policy rồi không ghim model vào argv

Path: bin/lib/dispatch_core.py:309-313 (build_codex_cmd). Cùng mẫu: build_grok_cmd :360, build_claude_cmd :339, build_dsh_cmd :453 (auto thì không --patch). _enforce_builder_policy resolve auto rồi giá trị trả về bị bỏ; argv dùng chuỗi "auto" gốc.

Reproducer (tested): build_codex_cmd("auto", "read-only", None, "text") ra ["codex","exec","-c","model_reasoning_effort=low","-s","read-only","--skip-git-repo-check"] — không có -m. run_vendor đi qua resolve_dispatch_target rồi truyền resolved_model (dispatcher.py:698) nên đường dispatch codex auto không dính lỗ này. Lỗ là API builder.

Tác hại: gọi builder với "auto" thì policy xét model đã resolve, process lại chạy default của CLI. Hai model có thể khác nhau; chốt contributor/free trên slug đã resolve không bảo vệ slug CLI tự chọn.

Sửa tối thiểu: argv dùng selector.model đã resolve, không bỏ -m khi input là "auto". dsh auto phải vẫn ghi patch của slug đã resolve.

## Giới hạn kiểm

- Không live vendor, không đọc ~/.hermes config, không gửi Telegram. Không chạy pytest full; chỉ probe targeted.
- Fallback watcher _fallback_parse_codex_json bịa slug từ key JSON ("usage-limits", "default-model") — tested. Đường sống parse_codex_models trả [] vì vendors.parse_codex_models có mặt. Không tính finding chừng nào import vendors không fail.
- apply_last_known_good bỏ catalog khi state=ready, models=[], error=None — tested. Doctor đặt error catalog_empty/catalog_parse_error nên đường đó không tái hiện từ detect(). Không nâng thành finding.
- Không kết luận catalog/version CLI thật từ tên lạ. Không claim Go sandbox hay vision live. Sensitive gate trên CLI/run_vendor giữ; lỗ vision ở API public và pdftoppm.
