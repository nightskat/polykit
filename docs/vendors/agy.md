# Agy (Antigravity) — CLI riêng, lane riêng

> Số liệu LIVE: [SNAPSHOT.md](SNAPSHOT.md) — máy sinh mỗi thứ 2 12:00. Ghi chú tay cập nhật 2026-08-03. Version live: `agy --version`. Catalog live: `agy models`.
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

## Vị trí trong PolyKit (đã tách, từ 0.4.0)
`agy` là **vendor đầy đủ** trong `REGISTRY`:

```
/polykit:doctor                                   # có dòng agy + số slug catalog
/polykit:dispatch agy -- "<prompt>"               # auto = chọn từ catalog LIVE
/polykit:dispatch agy claude-sonnet-4-6 -- "…"    # slug không-Gemini chạy được
```

- **Catalog động**: `detect()` chạy `agy models` và điền vào `state.json` → `watcher` diff
  được model vào/ra. Không có danh sách cứng nào trong code (đổi mùa là chuyện thường).
- **Catalog rỗng mà vẫn auth** → state `ready` + `error: catalog_empty`. Không im lặng khoe
  khoẻ, cũng không bịa list dự phòng.
- **Auth-check rớt vì hết quota** → `quota_capped`, không phải `installed_not_authed`
  (bảo đi login lại khi thật ra chỉ hết quota là sai lane).
- **`agy models` lỗi/rỗng không có dấu auth lỗi** → `auth_unverified`, không kết luận người dùng đã logout. Cần dispatch nhỏ khi thật sự cần xác nhận runtime.
- **`auto`** ưu tiên `gemini-3.6-flash-medium` **nếu còn trong catalog**; mất thì lấy slug
  `gemini-*` đầu tiên; hết nữa thì slug đầu danh sách.
- **Tương thích ngược**: `/polykit:dispatch gemini` vẫn có lane 1 = agy như cũ, không đổi
  hành vi, không hard-fail.

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
- **Lượt gửi ĐẦU TIÊN bị nuốt** (ghi nhận 2026-08-14): agy xoá prompt đầu và im lặng trong
  lúc tự kiểm tra eligibility của auth account. Dispatch một-phát-gửi-rồi-chờ (`echo prompt |
  polykit:dispatch agy --timeout 600`) sẽ treo tới hết timeout, 0 byte stdout, kết quả
  `ERROR: agy dispatch exceeded 600s`. **Cách né**: gửi 1 prompt mồi (bỏ kết quả đi) để agy
  check auth xong trước, rồi mới gửi prompt thật ở lượt kế — hoặc dùng `agy` tương tác
  (không qua dispatch một-phát) cho lượt đầu của phiên.

## `served_model` của agy — ý định, không phải bằng chứng
Dispatch gắn `result.served_model` = **slug đã GỬI cho agy** (sau khi `auto` được resolve từ
catalog live), không phải model agy báo lại đã thực sự chạy — agy không trả field đó. Xem
comment tại `bin/lib/dispatcher.py` (nhánh `elif vendor == "agy"`).

Hệ quả thực chiến: dispatch `agy` với `model=auto`, catalog live resolve ra một slug Gemini cụ
thể → dòng `[polykit] served: <slug>` xuất hiện ở **stderr** (không phải stdout) vì slug đã
resolve khác với `auto` đã gõ. Đây là "auto đã được giải quyết thành gì", KHÔNG phải bằng chứng
agy thật sự chạy đúng slug đó — agy có thể âm thầm phục vụ model khác mà không báo lại. Đọc
đúng chỗ: dòng `served:` ở stderr, hoặc field `served_model` trong `--result-json`. Ai redirect
stderr đi chỗ khác (hoặc chỉ đọc stdout) sẽ tưởng agy chạy đúng model yêu cầu.

So sánh: OpenRouter's `served_model` đọc thẳng từ field `model` trong response API — đó MỚI là
bằng chứng thật (router chọn gì thì response nói đúng cái đó). agy's `served_model` chỉ là ý
định phía client.

## PII
❌ KHÔNG gửi PII thật. Khử định danh trước hoặc chuyển về Claude host. Xem `../CHIA-VIEC.md` §PII.
