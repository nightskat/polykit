# REVIEW-GROK vòng 2 — cổng code-nopii

Reviewer: Grok-4.7, adversarial. Chỉ đọc repo + probe mock. Không sửa code sản phẩm, không commit, không gọi vendor, không network.
Phạm vi: cổng `data_class=code-nopii` (bypass cờ, PII lọt, attachment/cờ sensitive kể cả không file, CLI/API/builder/helper, result metadata).
Không đánh finding chỉ vì lane này unsandboxed — policy 22/10 cho phép khi cờ tường minh và cổng dữ liệu qua.
Probe: `/Users/nightskat/.hermes/cache/scratch/polykit-grok-r2-probe.py` bằng `~/.pyenv/versions/3.11.8/bin/python`. Runner/checker đều spy. Không chạy pytest full, không spawn opencode/hermes thật.

## Đã giữ (tested, không phải finding)

- Không cờ, cờ sai, `CODE-NOPII`, `code-nopii ` (space), hyphen Unicode, `True`: `sandbox_unsupported`, runner=0, `unsandboxed=false`.
- Lật `GO_SANDBOX_CONFINED=True` ở cả `dispatch_core` và `dispatcher` không mở builder. Public builder bắt `data_class` keyword-only (`TypeError` nếu truyền positional).
- `synthetic_vision` / `allow_sensitive_vision` / `sensitive_confirmation` không file: `vision_blocked`, runner=0, `unsandboxed=false`. CLI (`bin/dispatch.py` khoảng 429–433) truyền đủ ba cờ này vào `run_vendor`.
- Attachment (kể cả `" "`) trên `run_vendor` opencode và hermes: `vision_blocked` trước checker và trước spawn. Checker spy=0.
- PII (prompt giả `CCCD 012345678901`): `pii_detected`, runner=0, temp file đã xoá, JSON không chứa prompt hay stdout checker. Timeout checker (stdout/stderr giả có PII) → `pii_checker_failed`, không lọt vào `to_dict()`.
- Không có `pg-redact`: warning có mặt, text được chạy (đúng policy), attachment vẫn `vision_blocked`.
- Contributor + cờ: `contributor_model_blocked`, runner=0.
- Alias `OpenCode` / `opencode ` / `HERMES`: `unknown_vendor`, không rơi xuống shell template, runner=0.
- Prompt một argv `"-f /tmp/khach.pdf"` không bị tách thành cờ `-f`. File không vào argv.

## Findings

### 1. Medium — chặn PII/vision trước spawn vẫn ghi `unsandboxed=true`

Path: `bin/lib/dispatcher.py:655` (`go_optin = True` ngay sau cổng thứ nhất), `:749` (`_mark_go` ép `unsandboxed=True`), `:929` (bọc mọi kết quả của `_dispatch_go_adapter`), `:1154` (DispatchError của builder cũng set `unsandboxed` chỉ vì `data_class == "code-nopii"`). Builder kiểm lại ở `bin/lib/dispatch_core.py` (`_build_opencode_argv` / `_build_hermes_argv`).

`run_vendor` gọi `pg-redact` hai lần: một lần ở `_run_vendor`, một lần trong builder. Lần một exit 0 thì `go_optin` đã bật. Lần hai exit khác 0 thì không spawn, nhưng `_mark_go` vẫn đóng dấu đã chạy unsandboxed.

Reproducer (tested, checker spy trả 0 rồi 1, prompt giả có CCCD):

```
run_vendor("opencode", prompt_pii, model="auto", data_class="code-nopii", runner=spy, detector=ready)
```

Kết quả: `status=blocked`, `reason=pii_detected`, `unsandboxed=true`, `data_class=code-nopii`, runner=0. Summary nói "blocked trước detector/probe/vendor spawn" trong khi cờ nói đã unsandboxed. JSON không chứa prompt/checker output.

Cùng dấu trên helper, không cần checker hai pha: `_dispatch_go_adapter(opencode, attachments=["/tmp/khach.png"], data_class="code-nopii")` → `vision_blocked`, runner=0, `unsandboxed=true`. PII trên helper → `pii_detected`, `unsandboxed=true`, runner=0.

Tác hại: consumer chỉ nhìn `unsandboxed` sẽ tưởng lượt PII/attachment đã được phép chạy không sandbox. Comment `DispatchResult` nói blocked trước cổng phải để false, không tự nhận đã chạy. Không phải bypass spawn — vendor không được gọi. Timeout/lỗi sau khi CẢ HAI cổng đã qua thì `unsandboxed=true` là đúng spec, không nằm trong finding này.

Sửa tối thiểu: chỉ `go_optin=True` sau khi builder recheck cũng qua; mọi `status=blocked` trước spawn phải `unsandboxed=false`. Test checker không idempotent (0 rồi 1) và helper block.

### 2. Medium — helper hermes nuốt attachment rồi vẫn spawn

Path: `bin/lib/dispatcher.py:1134` (`build_hermes_cmd` không nhận `attachments`). `bin/lib/dispatch_core.py` `_build_hermes_argv` không có tham số attachment và không đưa attachment vào `evaluate_go_data_gate`. Nhánh opencode thì có, và đã chặn.

Reproducer (tested):

```
_dispatch_go_adapter(vendor="hermes", prompt="print(1)", attachments=["/tmp/khach-nhay-cam.pdf"], data_class="code-nopii", runner=spy, ...)
```

Kết quả: `status=ok`, `unsandboxed=true`, runner=1. Argv là `hermes -z print(1) --provider opencode-go -m deepseek-v4.1-flash --reasoning high`. Không có `-f`, path PDF không nằm trong argv.

Tác hại: helper nhận attachment rồi bỏ qua điều kiện "có attachment thì blocked". File không được gắn vào lệnh (không exfil qua argv), nhưng lượt unsandboxed vẫn chạy. `run_vendor` / CLI không dính: cùng attachment trên `run_vendor("hermes")` đã probe `vision_blocked`, runner=0, checker=0. Lỗ ở helper mà spec lô 11 bắt phải tự giữ cổng, cùng lớp với finding helper vòng 1.

Sửa tối thiểu: nhánh hermes của `_dispatch_go_adapter` truyền attachment (và cờ vision nếu có) vào cổng, hoặc từ chối tham số attachment trước khi gọi builder. Test hermes helper + attachment không được gọi runner.

### 3. Low — opt-in rồi skip vendor thì mất `unsandboxed` / `data_class`

Path: `bin/lib/dispatcher.py:726` (`state != READY` return `DispatchResult` không qua `_mark_go`). `run_vendor` chỉ ghép warning, không điền hai field.

Reproducer (tested, detector `path=None`, checker exit 0):

```
run_vendor("opencode", "print(1)", data_class="code-nopii", detector=not_installed, runner=spy)
```

Kết quả: `status=skipped`, `reason=not_installed`, `unsandboxed=false`, `data_class=null`, runner=0.

Tác hại: không phải bypass và không nhận nhầm đã chạy (false là chiều an toàn). Spec lô 11 yêu cầu JSON đường opt-in ghi hai field kể cả lỗi sau cổng. Audit không thấy caller đã khai `code-nopii` và cổng đã qua trước khi skip. Cùng cửa với `quota_capped` / `installed_not_authed` (cùng nhánh return).

Sửa tối thiểu: mọi return sau khi cổng đã qua phải set `data_class` và, nếu chưa spawn, `unsandboxed=false` kèm warning "cổng đã qua, chưa spawn" — hoặc `unsandboxed=true` nếu muốn đúng chữ "kể cả lỗi sau cổng", nhưng đừng để null.

## Không nâng thành finding

- Không có `pg-redact` mà text vẫn chạy: đúng chốt, warning có trong result, attachment vẫn chặn.
- Vòng `-f` sau cổng trong `_build_opencode_argv` là mã chết với list thường: cổng raise trước. Probe attachment không emit `-f`.
- Hermes unsandboxed đọc file trên đĩa khi prompt sạch: policy cho phép, không tính.
- `_chan_som` CLI chặn `-f` thật trước `run_vendor` nên JSON sớm có `data_class=null`. Vẫn `vision_blocked` và không đọc file. Không spawn.

## Xử lý sau review (điều phối xác minh)

- 4b252b4 (maker DeepSeek, agy timeout): sửa cả F1/F2/F3; blocked trước runner luôn false, helper Hermes truyền attachment vào gate, skipped giữ data_class và warning chưa spawn.
- Điều phối tự chạy full suite: 793 passed in 20.19s; git diff --check sạch.
- Điều phối tự tái hiện 3 nhánh × 2 vendor, không dùng probe của reviewer: cả 6 đúng, runner=0. Evidence: evidence/2026-10-22/review-round2-verification.json.
- Live lại sau sửa: opencode DeepSeek high, GLM max và Hermes default đều LIVE_OK; thiếu cờ/attachment/sensitive đều blocked. Evidence: evidence/2026-10-22/live-final-round2.json.

## Giới hạn kiểm

- Không live vendor, không `pg-redact` thật, không đọc credential. Checker/runner là spy.
- CLI subprocess opt-in không chạy (tránh spawn thật nếu cổng hở). Wiring CLI đọc tại `bin/dispatch.py` và kiểm qua `run_vendor` — hàm CLI gọi.
- Không claim số test full suite.
