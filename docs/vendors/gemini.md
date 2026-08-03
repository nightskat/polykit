# Gemini (Google) — bulk & value lane

> Cập nhật 2026-08-03. Version live: `/polykit:doctor`. Snapshot lúc viết: **gemini-cli 0.53.1**.
> ⚠️ Gemini CLI **không có lệnh `models list`** — muốn catalog live phải hỏi API (xem dưới)
> hoặc đọc tier trong `agy.sh`.

## Model đang có (snapshot 2026-08-03)
Lấy catalog live (lane API, chỉ model hỗ trợ `generateContent`):
```
python3 -c "import os,json,urllib.request,pathlib;k=os.environ.get('GEMINI_API_KEY') or (pathlib.Path.home()/'.gemini/api_key').read_text().strip();d=json.load(urllib.request.urlopen(urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models',headers={'x-goog-api-key':k})));print('\n'.join(sorted(m['name'].split('/')[-1] for m in d['models'] if 'generateContent' in m['supportedGenerationMethods'])))"
```
API trả **33 model `gemini-*`** (03/08). Nhóm dùng được cho text/vision:

| Nhóm | Slug |
|---|---|
| 3.6 (mới nhất) | `gemini-3.6-flash` |
| 3.5 | `gemini-3.5-flash`, `gemini-3.5-flash-lite` |
| 3.1 | `gemini-3.1-pro-preview`, `gemini-3.1-flash-lite`(`-preview`), `gemini-3.1-flash-image`(`-preview`) |
| 3.0 | `gemini-3-pro-preview`, `gemini-3-flash-preview`, `gemini-3-pro-image`(`-preview`) |
| 2.5 | `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-2.5-flash-image` |
| 2.0 (cũ, rẻ) | `gemini-2.0-flash`, `gemini-2.0-flash-lite` |
| Alias trôi | `gemini-flash-latest`, `gemini-flash-lite-latest`, `gemini-pro-latest` |
| Chuyên biệt | `*-tts`, `gemini-omni-flash-preview`, `gemini-2.5-computer-use-preview`, `gemini-robotics-er-*` |

Lane **CLI** hẹp hơn API: 8 model (2.5-flash/lite/pro, 3-flash/pro-preview, 3.1-flash-lite-preview,
3.1-pro-preview, 3.5-flash) — **chưa có 3.6**. Muốn 3.6 phải đi lane `agy`.

## Hai lane
| Lane | Là gì | Khi nào |
|---|---|---|
| `gemini` (CLI chính) | Gemini CLI, auth Google | Mặc định |
| `agy` (Antigravity) | Wrapper `agy.sh` bọc Antigravity CLI — quota RIÊNG với Gemini CLI, model mới hơn | Bulk rẻ, prose/classify — value winner; kênh xả khi lane chính hết quota |

### Lane `agy` chi tiết (cập nhật 2026-08-03)
Antigravity CLI không lưu được default model → wrapper `agy.sh` ghim model qua `--model`
mỗi lần gọi. **Default: Gemini 3.6 Flash (Medium) — model mới nhất.**

| Gọi | Slug thật gửi qua `--model` (03/08) |
|---|---|
| `agy.sh "<prompt>"` | `gemini-3.6-flash-medium` (default) |
| `agy.sh -t low\|high "<prompt>"` | `gemini-3.6-flash-low` / `-high` |
| `agy.sh -t f35[-low\|-high] "<prompt>"` | `gemini-3.5-flash-medium` / `-low` / `-high` — **tier tiết kiệm quota**, dùng cho bulk |
| `agy.sh -t pro-low\|pro-high "<prompt>"` | `gemini-3.1-pro-low` / `-high` — long-doc, việc khó |
| `agy.sh -- --model <slug> --effort high -p "…"` | Bypass wrapper (Claude/GPT-OSS trong Antigravity không có tier tắt) |

PolyKit map tier tự động trong `gemini_agy_tier()`: model `auto` hoặc `gemini-3.6-*` → tier
3.6, `gemini-3.5-flash*` → `f35*`, `gemini-3.1-pro*` → `pro-*`.

Quy tắc chọn: việc thường → default 3.6 · bulk/volume → `f35` · khó/dài → `pro-high`.
Lưu ý: `agy models` thỉnh thoảng trả output rỗng → doctor giữ catalog cũ + đánh dấu `stale`
(catalog trong state.json có thể cũ hơn thực tế script — script mới là nguồn đúng của lane này).

Máy mới không có Antigravity/`agy.sh`: lane tự degrade, dùng CLI chính. `agy` là tiện ích
máy-riêng, không phải thành phần bắt buộc của PolyKit.

## Cài & auth
```
npm install -g @google/gemini-cli
gemini      # rồi gõ /auth
# hoặc chỉ cần GEMINI_API_KEY cho lane API
```

## Gọi qua PolyKit
```
/polykit:dispatch gemini -- <prompt>
/polykit:dispatch gemini gemini-3.5-flash -- <prompt>
```

## Thế mạnh (bench + thực chiến)
- **Value winner** prose/classify/architecture (kém Opus ~0.1 điểm bench nội bộ, chi phí ~0).
- OCR/đọc ảnh tốt (Codex không làm được), bulk ≥20 file.
- Long-doc: Pro đọc `@url`/PDF dài.

## Điểm yếu đã ghi nhận bằng thực chiến — PHẢI CHẶN BẰNG QUY TRÌNH
**Case 2026-07-30 (file BCTC, bản "FIXED" do lane Agy làm):** để ép bảng cân đối "đẹp",
model **bịa số dư tiền** (hardcode 11.017.810.142đ trong khi sao kê chứng minh 3.036.393đ),
đóng dấu giá trị cache tự mâu thuẫn 3,03 tỷ (mở Excel bấm F9 là lòi), và **bịa doanh thu
tháng** = cả năm ÷ 12 cho 24 ô thiếu dữ liệu. Ba hành vi cùng một gốc: ưu tiên "trông đúng"
hơn "đúng".
→ **Luật khi giao việc cho Gemini**: mọi output số liệu bắt buộc chạy qua validator máy
(cân đối, đối chiếu nguồn) trước khi dùng; cấm giao việc "sửa cho khớp/cho đẹp" — chỉ giao
việc có đáp án kiểm chứng được. Xem `../CHIA-VIEC.md` §Gate.

## PII
❌ KHÔNG gửi PII thật. Khử định danh trước hoặc chuyển về Claude host. Xem `../CHIA-VIEC.md` §PII.

## Sự cố thường gặp
- Quota lane chính → chuyển `agy`/OR free (xem `/polykit:failover`).
- Headless subprocess trong sandbox hay timeout — chạy từ terminal user, đừng nhét vào sandbox.
- `agy models` đôi lúc trả output rỗng → doctor giữ catalog cũ + đánh dấu `stale` (hành vi đúng).
