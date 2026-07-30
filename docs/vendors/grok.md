# Grok (xAI) — lane phụ / second opinion

> Cập nhật 2026-07-30. Model/version hiện tại: chạy `/polykit:doctor`. Snapshot lúc viết:
> grok CLI 0.2.x, model `grok-4.5`.

## Cài & auth
```
# cài Grok CLI theo hướng dẫn xAI hiện hành
grok        # lần đầu sẽ dẫn qua auth
```

## Gọi qua PolyKit
```
/polykit:dispatch grok -- <prompt>
```

## Vai trò
- **Second opinion / debate**: thêm một góc nhìn độc lập khi 2 vendor chính bất đồng
  (dùng trong cross-vendor review, N-way debate).
- Kiểm tra nhanh dữ liệu dump (case đã dùng: grok dump 149 ô đối chiếu Excel).
- KHÔNG phải lane chủ lực — chưa có đủ bench nội bộ để giao việc một mình; kết quả
  nên có vendor khác đối chiếu.

## PII
❌ KHÔNG gửi PII thật. Xem `../CHIA-VIEC.md` §PII.

## Sự cố thường gặp
- 402 (hết credit) → doctor chuyển state `quota_capped`, dispatch degrade — không crash.
  Đó là hành vi thiết kế (milestone M2).
