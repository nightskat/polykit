# OpenRouter — free tier & bypass cap

> Cập nhật 2026-07-30. OR là lane **API-key**, không phải CLI — doctor không track state machine
> cho nó (không có `not_installed/authed`); có key là chạy, sai key thì dispatch báo lỗi mềm.

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
