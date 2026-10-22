# Lô triển khai

Base: 7596d26feb187b95b19a8d87e30d4e7ac6097138. Baseline: 275 passed.
Maker: agy gemini-3.8-flash-high; fallback: Hermes opencode-go deepseek-v4.1-flash high.
Mỗi lô chạy toàn bộ pytest độc lập trước commit; không maker tự commit.

1. model_policy.py + test: chuẩn hoá selector, contributor cấm, free explicit-only.
2. vendor_config.py + vendors.json + test: resolver/default/profile; catalog advisory.
3. dispatch_core.py + test: builder opencode/hermes, guard entrypoint.
4. dispatcher.py + dispatch.py + test: policy trước probe, adapter và sandbox fail-closed.
5. vendors.py + doctor.py + test: detect/probe, timestamp, cảnh báo ZDR.
6. quota.py + doctor_quota.py + test: quota group, ba cửa sổ.
7. watcher.py + test: catalog JSON parser, stale last-known-good, ZDR.
8. vision.py + test: cổng PII trước I/O, MIME/capabilities/PDF.
9. dispatcher.py + dispatch.py + test: nối vision CLI/lib, xác nhận mỗi lượt.
10. README/commands/docs: cập nhật theo bằng chứng (chia nhỏ nếu cần).
11. Grok-4.7 adversarial review; finding thật giao maker lô riêng.
12. Điều phối tự live test tổng hợp và báo cáo <=60 dòng.

Adapter chưa chứng minh sandbox thì blocked, trừ ngoại lệ Tuan chốt trong BRIEF-SOL-2.md: text code-nopii tường minh được chạy unsandboxed qua cổng kiểm prompt; attachment/vision vẫn chặn.
Không dữ liệu khách hàng, không sửa cấu hình/credential cá nhân, không push/merge.

## Mốc đã kiểm độc lập
- Lô 1: 07a2160 (agy), đã trả maker sửa bypass value-object/provider/source.
- Lô 2: 02cca19 (agy); lô 2c bef1559 (DeepSeek sau agy timeout): GLM prefix vẫn max.
- Lô 3: 1945134 (agy), xoá cờ evidence_sandbox bypass; Go đóng mặc định.
- Lô 4+9: 6a6b433 (agy → DeepSeek sau timeout), CLI/lib/API/vision gate.
- Migration test tách lô 2b/4b/4c/4d; commit c8a3d38 (agy).
- Lô 5: 3bd84d7 (agy), doctor/catalog/ZDR.
- Lô 6: 35171a0 (agy), quota group và ba cửa sổ.
- Lô 7: 80ded8b (agy → DeepSeek sau timeout), watcher LKG/ZDR.
- Lô 8: 8a6e625 (agy), gate vision fail-closed.
- Lô 10: 6e1f638 (agy), docs nêu rõ chưa operational.
- Điều phối chạy full pytest riêng trước từng commit cuối: 683 passed, không tin output maker.
- Các lô tệp độc lập đã chạy song song; mọi acceptance/commit chờ full suite xanh.
- Grok review đang chạy trên diff 7596d26..6e1f638; live test/báo cáo chưa nghiệm thu.
- TÍNH NĂNG CÒN CHẶN: Go read-only/workspace-write chưa chứng minh confinement;
  vision transport và xác nhận trusted UI mỗi lượt chưa operational. Không bật lane PGBank.

## Vòng 2 — ngoại lệ code-nopii (BRIEF-SOL-2.md)
13. e856d43: commit docs vòng 1 dựa trên live-results.json.
14. 57e8328: cổng code-nopii, checker prompt và metadata; agy không ra kết quả → DeepSeek; điều phối 770 passed.
15. 6780e42: README/dispatch docs và live evidence; agy timeout → DeepSeek; điều phối 770 passed.
16. Grok-4.7 review riêng: 2 Medium + 1 Low (REVIEW-GROK-ROUND2.md).
17. 4b252b4: sửa cả 3 findings; agy timeout → DeepSeek; điều phối 793 passed + 6 probe độc lập.
18. Live cuối: DeepSeek high / GLM max / Hermes default LIVE_OK; không cờ/attachment/sensitive blocked; free explicit lỗi vendor.
19. Vision trực tiếp ảnh tổng hợp 3/3 trường; dispatch vision và PII vẫn đóng. Báo cáo BAO-CAO-2026-10-22.md.
