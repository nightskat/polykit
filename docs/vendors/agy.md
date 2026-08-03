# Agy (Antigravity) — CLI riêng, lane riêng

> Cập nhật 2026-08-03. Version live: `agy --version`. Catalog live: `agy models`.
> Snapshot lúc viết: **agy 1.1.9**, binary `~/.local/bin/agy` (~165MB, self-contained).

**Agy KHÔNG phải một lane của Gemini.** Đây là CLI độc lập của Antigravity:
- **Quota riêng**, không đụng quota Gemini CLI hay Gemini API.
- **Inventory đa nhà**: ngoài Gemini còn có Claude và GPT-OSS (xem bảng dưới).
- Auth riêng của Antigravity, không dùng `/auth` của Gemini CLI.

Sở dĩ PolyKit gọi nó bên trong vendor `gemini` là **giới hạn hiện tại của code**, không phải
bản chất của agy — xem §"Vị trí trong PolyKit".

## Model đang có (snapshot 2026-08-03 — `agy models` trả 11 slug)
| Nhà | Slug | Ghi chú |
|---|---|---|
| Google | `gemini-3.6-flash-high` / `-medium` / `-low` | Mới nhất; **3.6 chỉ có ở lane này**, Gemini CLI chưa có |
| Google | `gemini-3.5-flash-high` / `-medium` / `-low` | Tier tiết kiệm quota, dùng cho bulk |
| Google | `gemini-3.1-pro-high` / `-low` | Long-doc, việc khó |
| Anthropic | `claude-sonnet-4-6`, `claude-opus-4-6-thinking` | Model do Antigravity phục vụ sẵn — **khác hoàn toàn** chuyện spawn Claude Code qua CLI khác (cái đó vẫn cấm, xem SPEC P3) |
| OpenAI (OSS) | `gpt-oss-120b-medium` | — |

Effort nằm **trong tên slug** (`-low/-medium/-high`), không có cờ `--effort` riêng cho tier
shortcut. Đừng suy inventory từ wrapper: `agy models` mới là nguồn đúng.

## Cách gọi
CLI gốc:
```
agy --model <slug> -p "<prompt>"
agy models          # inventory live
agy --help          # help gốc (wrapper KHÔNG phải help đầy đủ)
```

Wrapper tiện tay `~/scripts/agy.sh` — sinh ra vì agy **không lưu được default model**
(đã dò `~/.config`, `~/.gemini/antigravity/*.pbtxt`, `app_storage.json` — chỉ có enum mờ
`last_selected_agent_model`), nên phải truyền `--model` mỗi lần:

| Gọi | Slug thật |
|---|---|
| `agy.sh "<prompt>"` | `gemini-3.6-flash-medium` (default wrapper) |
| `agy.sh -t low\|high` | `gemini-3.6-flash-low` / `-high` |
| `agy.sh -t f35[-low\|-high]` | `gemini-3.5-flash-medium` / `-low` / `-high` |
| `agy.sh -t pro-low\|pro-high` | `gemini-3.1-pro-low` / `-high` |
| `agy.sh -- <raw args>` | Bypass wrapper — **cách duy nhất** chạm `claude-*` / `gpt-oss-*` |

Wrapper chỉ có 8 tier Gemini; 3 model Claude/GPT-OSS **cố ý không hard-code** vì availability
đổi theo mùa.

## Vị trí trong PolyKit (đang lệch — biết để không mắc bẫy)
Code hiện tại **chưa có vendor `agy`** trong `REGISTRY`. `dispatch.py` coi agy là *lane 1 của
vendor `gemini`*, và `is_agy_model()` chỉ nhận `auto` + slug `gemini-3.6/3.5/3.1-pro`. Hệ quả:

- `/polykit:dispatch gemini -- "…"` → **đi agy** (lane 1) nếu có `agy.sh`. ✅
- `/polykit:dispatch gemini claude-sonnet-4-6 -- "…"` → agy bị bỏ qua ("model not supported"),
  rơi xuống Gemini CLI rồi **fail**. ❌ Muốn dùng Claude/GPT-OSS của agy: gọi tay
  `agy --model claude-sonnet-4-6 -p "…"`.
- `doctor` **không** báo trạng thái agy: agy chết → không hiện `not_installed`, chỉ thấy
  dispatch gemini tự degrade xuống lane 2.

→ Backlog: tách `agy` thành vendor riêng trong `REGISTRY` (detect `agy`, `agy models` làm
catalog, quota riêng) để doctor/watcher nhìn thấy nó. Xem `../BACKLOG.md`.

## Điểm yếu đã ghi nhận bằng thực chiến
**Case 2026-07-30 (file BCTC, bản "FIXED" do lane agy làm):** để ép bảng cân đối "đẹp", model
**bịa số dư tiền** (hardcode 11.017.810.142đ trong khi sao kê chứng minh 3.036.393đ), đóng dấu
giá trị cache tự mâu thuẫn 3,03 tỷ, và **bịa doanh thu tháng** = cả năm ÷ 12 cho 24 ô thiếu dữ
liệu. → Mọi output số liệu từ lane này phải qua validator máy; cấm giao việc "sửa cho khớp".
Xem `../CHIA-VIEC.md` §Gate.

## Sự cố thường gặp
- `agy models` thỉnh thoảng trả output rỗng → cache cross-CLI giữ catalog cũ + đánh dấu
  `stale`. Chạy lại thường là ra.
- Máy không có Antigravity: `agy.sh` vắng → dispatch gemini tự tụt lane 2 (CLI) rồi lane 3
  (API). Agy là tiện ích máy-riêng, **không phải thành phần bắt buộc** của PolyKit.

## PII
❌ KHÔNG gửi PII thật. Khử định danh trước hoặc chuyển về Claude host. Xem `../CHIA-VIEC.md` §PII.
