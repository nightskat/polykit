# OpenRouter — free tier & bypass cap

> Cập nhật 2026-08-03. OR là lane **API-key**, không phải CLI — doctor không track state machine
> cho nó (không có `not_installed/authed`); có key là chạy, sai key thì dispatch báo lỗi mềm.

## Model free đang sống (snapshot 2026-08-03 — 17 slug)
Watcher tự diff danh sách này mỗi lần chạy; **danh sách dưới hết hạn nhanh nhất trong repo.**

| Nhóm | Slug |
|---|---|
| Default PolyKit | `nvidia/nemotron-3-nano-30b-a3b:free` ✅ còn sống |
| Router | `openrouter/free` (tự chọn model free) |
| NVIDIA Nemotron | `nemotron-3-nano-omni-30b-a3b-reasoning`, `nemotron-3-super-120b-a12b`, `nemotron-3-ultra-550b-a55b`, `nemotron-nano-12b-v2-vl` (vision), `nemotron-nano-9b-v2`, `nemotron-3.5-content-safety` — đều `:free` |
| Google | `google/gemma-4-26b-a4b-it:free`, `google/gemma-4-31b-it:free` |
| Khác | `openai/gpt-oss-20b:free`, `cohere/north-mini-code:free`, `inclusionai/ling-3.0-flash:free`, `poolside/laguna-s-2.1:free`, `poolside/laguna-xs-2.1:free` |
| Không phải chat | `google/lyria-3-clip-preview`, `google/lyria-3-pro-preview` (sinh nhạc) |

Đã chết: `google/gemini-2.0-flash-exp:free` (404 từ 13/07 — chính là lý do đổi default sang
nemotron). Lấy list live **đúng tiêu chí watcher đang dùng** (`pricing.prompt == "0"`, chứ
không phải lọc theo hậu tố `:free` — nên `openrouter/free` và `lyria-3-*` mới lọt vào):
```
curl -s https://openrouter.ai/api/v1/models | python3 -c "import sys,json;print('\n'.join(sorted(m['id'] for m in json.load(sys.stdin)['data'] if m.get('pricing',{}).get('prompt')=='0')))"
```

## Cài & auth
1. Lấy key free: [openrouter.ai/keys](https://openrouter.ai/keys). Nạp $10 một lần → free tier
   nâng lên **1.000 requests/ngày** cho model `:free`.
2. Một trong hai:
   - `export OPENROUTER_API_KEY=...` (Windows: `setx OPENROUTER_API_KEY ...`)
   - Ghi key vào `~/.config/openrouter/key` (bền, không cần export mỗi shell)

## Gọi qua PolyKit
```
/polykit:dispatch openrouter -- <prompt>                          # model free mặc định
/polykit:dispatch openrouter <provider/model:free> -- <prompt>    # chỉ định model
```
Model free đổi liên tục theo mùa — **đừng hardcode tên model trong script**; watcher diff
danh sách OR free hàng tuần, xem `/polykit:watcher`.

## Khi nào dùng
| Việc | Vì sao |
|---|---|
| Classify volume >100/h | Free, 1K RPD |
| OCR batch lớn | Qua model vision free |
| Test model niche | Không cần cài CLI mới |
| Bypass khi vendor chính hết quota | Lane failover cuối (xem `/polykit:failover`) |

## Khi nào KHÔNG dùng
- Việc cần chất lượng chốt (số liệu tài chính, pháp lý) — free tier chất lượng dao động,
  chỉ dùng làm nháp/phân loại, có validator hoặc vendor khác kiểm.

## PII
❌ TUYỆT ĐỐI KHÔNG gửi PII thật — OR route qua bên thứ ba đa dạng, không kiểm soát được
data policy của từng provider. Nghiêm hơn mọi lane khác. Xem `../CHIA-VIEC.md` §PII.
