# Hồ sơ QA — chuỗi 12 vòng, 17/08/2026

Thư mục này là **bản ghi quá trình**, không phải tài liệu dùng sản phẩm.
Người mới dùng PolyKit đọc `../../README.md`.

## Chuyện gì đã diễn ra

`config/vendors.json` được nâng từ v1 (4 vendor, 2 trường) lên v3 (7 vendor, đủ trường
để dispatch mà không phải dò lại cú pháp CLI). Việc nâng chạy qua **12 vòng** theo chuỗi:

```
maker (agy)  →  QA khác họ (Grok)  →  cổng chặn bằng script (không do AI kiểm)
```

Test: **114 → 153**. Vòng 12 QA kết luận `KHÔNG TÌM RA CHỖ HỎNG`.

## Đọc gì

| Loại file | Nội dung |
|---|---|
| `DE-BAI-*.md` | Đề bài giao maker / QA từng vòng |
| `BAO-CAO-*.md` | Maker khai đã làm gì |
| `DAP-*.md` | QA chạy lại và bắt lỗi |
| `TRANG-THAI-*.md` | Kết quả cổng chặn tự động từng vòng |
| `chay-vong*.sh` | Script chạy cả dây chuyền |

## Năm cổng chặn — thứ đáng mang đi dùng lại

Mỗi cổng sinh ra từ một lỗi đã trả giá thật, và **không cái nào do AI tự chấm**:

1. `pytest` — 0 failed, số test không được giảm
2. Mọi vendor `--dump-config` phải exit 0 *(bắt lỗi "vá quá tay chặn cả cái đúng")*
3. `git diff --quiet config/vendors.json` *(bắt việc sửa dữ liệu đã kiểm chứng)*
4. `grep "dry-run" commands/failover.md` *(bắt việc plugin gửi thông báo thật)*
5. `grep` báo cáo tìm lệnh không chạy được *(bắt việc khai khống)*

## Bốn bài học

- **Điều kiện nghiệm thu một bản vá: bẻ hành vi → test phải ĐỎ.** Xanh nghĩa là test rỗng ruột.
  Ba lần trong chuỗi này, test xanh mà không bảo vệ gì.
- **Test remap sang vendor thật là mất tác dụng.** Dùng vendor giả trong `tests/conftest.py`.
- **Siết một chiều thường mở ra chiều kia.** Vá xong luôn hỏi: "cái này vừa mở cửa nào?"
- **Đề bài không ràng buộc được hành vi, chỉ tạo dấu vết kiểm được.** Việc bắt lỗi là của
  vòng sau, bằng cách chạy lại đúng lệnh đã khai.
