---
description: Dispatch task tới vendor (agy|dsh|codex|gemini|claude|grok|openrouter|opencode|hermes), degrade nếu thiếu
argument-hint: "<vendor> [model] -- <prompt>"
allowed-tools: Bash
---
Parse `$ARGUMENTS`: token đầu = vendor, phần sau `--` = prompt (mặc định model=auto).
`--timeout` mặc định theo vendor (hoặc 120s), **trần cứng 600s** — truyền cao hơn bị chặn ngay ở cổng validate
(`ERROR: dispatch blocked: timeout must be a positive integer 1-600`), không chạy vendor.

## Defaults & Hồ sơ
- **codex**: Mặc định `gpt-6.1-sol`, reasoning effort `low`.
- **dsh**: Mặc định `deepseek-v4-pro`, reasoning effort `high`.
- **agy**: Giữ nguyên `gemini-3.8-flash-high`.
- **opencode & hermes** (Go adapters): Cùng provider `opencode-go`, chia sẻ chung quota group `opencode-go`.
  - Mặc định: `deepseek-v4.1-flash` (reasoning effort `high`).
  - Profile `--profile glm-5.3-flash`: model `glm-5.3-flash` (reasoning effort `max`).

## Cờ mở rộng (actual flags)
- `--profile <name>`: Chọn profile cấu hình vendor (vd: `glm-5.3-flash`, `kho`, `claude`).
- `--provider <name>`: Chỉ định provider tường minh (vd: `opencode-go`).
- `--effort <level>`: Chọn reasoning effort (`low`, `medium`, `high`, `max`...).
- `-f, --file <path>`: Đính kèm file ảnh/PDF cho vision (lặp lại được: `-f a.png -f b.png`).
- `--synthetic-vision`: Khai báo tường minh file đính kèm là dữ liệu tổng hợp / synthetic.
- `--allow-sensitive-vision`: Cờ cho dữ liệu nhạy cảm (mặc định bị chặn do trustedUI chưa hỗ trợ xác nhận mỗi lượt).
- `--prompt-file <path>`: Đọc prompt từ file thay vì stdin (bắt buộc cho prompt dài/đa dòng/có dấu).
- `--result-json`: Trả về kết quả JSON đầy đủ (`status`, `served_model`, `exit_code`, `warnings`).
- `--stream-diagnose`: Chạy vendor ở chế độ stream để bắt output khi timeout (BUG-6).
- `--doctor`: Chạy lệnh `verify_cmd` của vendor.
- `--dump-config`: In cấu hình vendor đã giải quyết và thoát (0 token).
- `--allow-unknown-model`: Cho phép gọi model chưa có trong catalog JSON (catalog mang tính advisory).
- `--no-traps`: Ẩn cảnh báo trap trên stderr.

## ⚠️ Trạng thái Go Dispatch & Vision (CHƯA OPERATIONAL — CHƯA LIVE TEST)
- **Go adapters (`opencode`, `hermes`) & Vision**: Vẫn **bị chặn (blocked), chưa operational**. Cổng kiểm soát an toàn (gate) đã được tích hợp cả ở CLI và lib, không còn pending integration.
  - Go sandbox chưa được kiểm chứng cách ly an toàn (`no proven confinement`) → dispatch bị chặn fail-closed ngay cổng với `status=blocked`, reason `sandbox_unsupported`. **Không nói Go dispatch hay vision đang hoạt động.**
  - Cổng Vision: Dữ liệu nhạy cảm / sensitive vision mặc định **bị chặn** (`vision_blocked`) do **trustedUI chưa hỗ trợ** xác nhận mỗi lượt. Cam kết lưu trữ ZDR (Zero Data Retention) **không thay thế** các cổng an toàn.
- **Chính sách Model & Routing**:
  - Model `*-contributor`: **Cấm tuyệt đối** trên mọi vendor (nguy cơ train trên dữ liệu), không cho bypass.
  - Model `*-free`: **Chỉ cho phép khi chọn tường minh** (`explicit-only`); cấm tuyệt đối dùng làm default, auto router, hoặc failover.
  - OpenRouter: Chặn các router generic chưa rõ đích (`auto`, `free`, `free-router`, `:free`) và model `:free` (`unresolved destination`).
  - Catalog models: Mang tính chất **khuyến cáo (advisory)**, không phải whitelist cứng chặn oan model mới.
- *Nghiệm thu 22/10/2026*: Codex/Agy default đã trả đúng `LIVE_OK`; các thử nghiệm Go/vision trả blocked, chưa có inference Go hay phép chấm OCR. Xem kết quả thật và việc còn chặn tại `docs/plans/BAO-CAO-2026-10-22.md`.

## Prompt NGẮN, một dòng → stdin
```
echo "<prompt>" | python3 "${CLAUDE_PLUGIN_ROOT}/bin/dispatch.py" <vendor> [model] --result-json
```

## Prompt DÀI / nhiều dòng / có dấu tiếng Việt → `--prompt-file`
`echo "..."` **vỡ** với prompt dài: quoting, xuống dòng và dấu tiếng Việt hỏng ở tầng shell
trước khi tới dispatch. Ghi ra file rồi truyền đường dẫn:
```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/dispatch.py" <vendor> [model] --prompt-file <path> --result-json
```
File không đọc được hoặc rỗng → exit 2, chặn trước khi gọi vendor.

## Đọc kết quả & Bằng chứng Model Phục vụ (`served_model`)
Nguồn chính thức là `--result-json`: `status`, `served_model`, `exit_code`, `warnings`.

- **Nguyên tắc xác thực bằng chứng (`evidence`)**:
  - Khi output là plaintext hoặc không có trusted envelope (chạy CLI subprocess như agy, gemini CLI, codex, dsh), `served_model = None` (`null` trong JSON). Việc ghim model tường minh (`explicit pin` trên argv/CLI) **KHÔNG chứng minh** model thực tế đã phục vụ.
  - JSON do assistant (model completion) tự sinh trong văn bản trả về chứa `model`/`modelVersion` **không phải metadata tin cậy**.
  - **Chỉ có** trường `model` từ HTTP response của OpenRouter hoặc top-level `modelVersion` từ Gemini API response envelope mới được công nhận là bằng chứng xác thực (`evidence`).
- Dòng `[polykit] served: <model>` chỉ in ra stderr khi có evidence xác nhận model thật **KHÁC** model đã yêu cầu (ví dụ router OpenRouter trả về model cụ thể khác slug yêu cầu). Khi trùng nhau hoặc khi không có trusted envelope (`served_model=None`), dòng này không in ra.

⚠️ Mã thoát của vendor CLI không đáng tin. Nghiệm thu bằng nội dung/kích thước kết quả,
và bằng **dấu vết phụ** (file nó bảo đã ghi có thật không, chạy lại có ra đúng số không).

## 🐞 Thấy bug thì phải GHI LẠI — không được nuốt
Agent nào dùng PolyKit mà gặp hành vi sai (vendor chết mà exit 0, cờ không có tác dụng,
tài liệu mô tả sai, prompt bị nuốt…) thì **bắt buộc**:

1. **Ghi ngay** vào `docs/BUGS.md` của repo PolyKit — một mục có: ngày, lệnh đã chạy nguyên văn,
   cái đã đo được (không phải cái đoán), và việc cần làm.
2. **Sửa luôn nếu sửa được trong phiên** rồi ghi kèm bằng chứng đã sửa (test hoặc live test).
   Không sửa được thì để nguyên mục đó ở trạng thái MỞ, đừng đóng khống.
3. **Đừng để file bug nằm untracked** — đã xảy ra 18/08: bug ghi xong nằm ngoài git suốt một ngày,
   không ai thấy, bản cài và repo tách nhau lúc nào không biết.

Trước khi ghi bug mới, đọc `docs/BUGS.md` xem đã có chưa.
