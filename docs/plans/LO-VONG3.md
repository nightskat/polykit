# Lô vòng 3
Base 7fb0920. Điều phối không viết code sản phẩm; mọi maker/reviewer qua bin/dispatch.py.
1. Generator deterministic + manifest + ground truth typed, sáu trang synthetic và PDF.
2. Gate synthetic allowlist/hash + integration dispatch + negative tests.
3. Runner/scorer typed + live bench DeepSeek/GLM ảnh/PDF + vnocr local.
4. BUG-14 doctor/probe chung + regression.
5. Toolkit README chỉ mục PolyKit; Grok review, sửa finding, báo cáo ≤60 dòng.
Sau mỗi lô điều phối tự chạy toàn bộ pytest; commit riêng ghi vendor maker. Timeout/lỗi wrapper ghi docs/BUGS.md trước fallback; lô >600s chia nhỏ. Không push/merge/credential/PII/contributor.
