# Grok (xAI) — lane phụ / second opinion

> Số liệu LIVE: [SNAPSHOT.md](SNAPSHOT.md) — máy sinh mỗi thứ 2 12:00. Ghi chú tay cập nhật 2026-08-03. Version live: `/polykit:doctor`. Catalog live: `grok models`.
> Snapshot lúc viết: **grok CLI 0.2.118 [stable]**.

## Model CLI đang có (snapshot 2026-08-03)
| Slug | Ghi chú |
|---|---|
| `grok-4.5` | **Default và là model DUY NHẤT** CLI liệt kê — không cần ghim `-m` |

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

## Điểm yếu đã ghi nhận bằng thực chiến
**2026-07-30**: 2 lần timeout liên tiếp (120s rồi 480s) với task codegen dài (~250 dòng
Python) qua CLI dispatch — trong khi cùng ngày trả lời brief phân tích ~5KB tốt trong
thời hạn. → Lane phù hợp: ý kiến/second-opinion/phân tích ngắn. KHÔNG giao codegen dài
qua dispatch; cần Grok code thì chia task ≤50 dòng hoặc đổi lane.

## Sự cố thường gặp
- 402 (hết credit) → doctor chuyển state `quota_capped`, dispatch degrade — không crash.
  Đó là hành vi thiết kế (milestone M2).
