# Codex (OpenAI) — code review & audit lane

> Số liệu LIVE: [SNAPSHOT.md](SNAPSHOT.md) — máy sinh mỗi thứ 2 12:00. Ghi chú tay cập nhật 2026-08-03. Version live: `/polykit:doctor`. Catalog live: `codex debug models`.
> Snapshot lúc viết: **codex-cli 0.146.0**, default **`gpt-5.6-sol`** (0.145 default là terra —
> default đổi theo bản CLI, đừng ghim vào script).

## Model CLI đang có (snapshot 2026-08-03)
| Slug | Effort mặc định | Ghi chú |
|---|---|---|
| `gpt-5.6-sol` | low | **Default CLI**. Frontier agentic coding |
| `gpt-5.6-terra` | medium | Default cũ của 0.145 |
| `gpt-5.6-luna` | medium | — |
| `gpt-5.5` | medium | Lane review nhanh đã bench nội bộ |
| `gpt-5.4` | medium | Lane adversarial cũ |
| `gpt-5.4-mini` | medium | Rẻ nhất |
| `codex-auto-review` | medium | Ẩn (`visibility: hide`) — CLI tự dùng, không gọi tay |

Effort hỗ trợ (mọi model 5.6): `low · medium · high · xhigh · max · ultra`.
Bump effort trước khi bump model.

## Cài & auth
```
npm install -g @openai/codex   # hoặc theo hướng dẫn OpenAI hiện hành
codex login
```
Doctor báo `installed_not_authed` → chạy `codex login` là xong.

## Gọi qua PolyKit
```
/polykit:dispatch codex -- <prompt>
/polykit:dispatch codex gpt-5.5 -- <prompt>     # ghim model khi cần
echo "prompt" | python3 bin/dispatch.py codex --result-json
```

## Thế mạnh (bench + thực chiến)
- **Adversarial code review** — lane số 1, hơn cả Claude Opus trong đối chiếu nội bộ.
- Audit văn bản/số liệu chặt chẽ, viết báo cáo rà soát có cấu trúc tốt.
- Text-only: không đọc ảnh (OCR skip).

## Điểm yếu đã ghi nhận bằng thực chiến — PHẢI CHẶN BẰNG QUY TRÌNH
**Case 2026-07-30 (file BCTC):** Codex tự liệt kê 9 câu hỏi "cần xác minh trước khi sửa" trong
báo cáo, rồi **vẫn xuất file đã sửa theo giả định của chính nó** khi chưa có câu trả lời nào
(tự phân loại khoản vay 2,174 tỷ vào dài hạn → toàn bộ LNST/VCSH đổi theo). Văn bản đúng quy
trình, sản phẩm sai quy trình.
→ **Luật khi giao việc cho Codex**: output nào kèm "câu hỏi chưa trả lời" thì CHỈ nhận phần
báo cáo, KHÔNG nhận file/code đã sửa. Xem gate ở `../CHIA-VIEC.md` §Gate.

## PII
❌ KHÔNG gửi PII thật (tên, CIF, MST, số HĐ, số dư của khách hàng thật). Khử định danh trước
hoặc chuyển việc về Claude host. Xem `../CHIA-VIEC.md` §PII.

## Sự cố thường gặp
- 429/quota → failover sang Gemini lane review (xem `/polykit:failover`).
- Model list đổi thường xuyên (0.14x đổi default liên tục) — đừng hardcode model trong script,
  để `auto` trừ khi có lý do ghim.
