# Chia việc đa vendor — playbook

> Cập nhật 2026-07-30. Đúc từ thực chiến (case BCTC 30/07: 3 vendor cùng đọc 1 file, 3 kết quả
> khác nhau ở đúng những chỗ cần biết ý người). Guide từng vendor: `vendors/*.md`.

## Nguyên tắc lõi

1. **Model không thiếu năng lực — thiếu người hướng dẫn ở chỗ rẽ.** Trước khi chia việc,
   liệt kê các "chỗ rẽ" (điểm task có ≥2 cách làm hợp lý, chọn sai là hỏng). Chỗ rẽ chưa có
   đáp án của người → KHÔNG dispatch phần đó, chỉ dispatch phần đã rõ.
2. **Maker–checker khác vendor.** Vendor nào làm thì vendor khác (hoặc Claude host) review.
   Không nghiệm thu output vendor bằng chính vendor đó.
3. **Kết quả số liệu phải qua validator máy** (script kiểm tra tất định), không nghiệm thu
   bằng mắt hay bằng lời model tự khai.

## Gate — học từ 2 vụ fail thật (2026-07-30)

| Vụ | Vendor | Hành vi | Gate chặn |
|---|---|---|---|
| Bịa số ép cân đối | Gemini/Agy | Hardcode tiền 11 tỷ cho bảng "đẹp", cache tự mâu thuẫn | Validator máy: cân đối + đối chiếu nguồn từng số |
| Sửa theo giả định | Codex | Tự liệt kê 9 câu hỏi chưa trả lời, vẫn xuất file đã sửa | **Câu hỏi mở > 0 → chỉ nhận báo cáo, không nhận file/code đã sửa** |

Hai gate này áp cho MỌI vendor, mọi task số liệu — không phải phạt riêng ai.

## PII — luật cứng

- PII thật (tên KH, CIF, MST, số HĐ, số dư, sao kê): **chỉ Claude host** được xử lý.
- Muốn dispatch việc có PII → **khử định danh trước** (thay tên/CIF bằng mã, làm tròn hoặc
  xáo số nếu bản chất việc cho phép), hoặc tách phần không-PII ra mà giao.
- OpenRouter nghiêm nhất: không bao giờ, kể cả "chỉ một cái tên".
- Áp cho cả file đính kèm, screenshot, và dữ liệu nhét trong prompt.

## Vai của từng lane (cập nhật 2026-08-03)

Nghĩ theo **vai trong một đội**, không theo "model nào giỏi hơn":

| Vai | Lane | Việc đúng vai |
|---|---|---|
| Người quyết | **bạn** | Chốt scope, ký, việc pháp nhân: submit, tiền, dữ liệu thật |
| Điều phối + nghiệm thu | **Claude host** | Chia việc, khử trùng lặp, tổng hợp, phán xét kết quả vendor |
| Việc cơ khí nhiều bước | **Claude lane rẻ** (Sonnet/Haiku) | Đọc file, bóc email, duyệt web — đừng để lane đắt gõ tay |
| Senior + phản biện | **Codex** | Dựng code, adversarial review có cấu trúc |
| QA / "đập" | **Grok** | Red-team, tìm giả định lạc quan, bắt số ảo. Không dùng một mình |
| Maker | **agy** (Antigravity) | Draft, prose, đọc tài liệu dài. **Quota riêng** với Gemini CLI |
| Dự phòng maker | **Gemini CLI/API** | Bulk OCR ảnh, long-doc — kênh xả khi agy hết quota |
| Ca đêm | **OpenRouter free** | Việc "lặp N lần, không cần thông minh": classify, tag, batch |
| Hồ sơ mật | **Công cụ cục bộ** | OCR/tìm kiếm on-device — lane duy nhất được chạm dữ liệu thật |
| Thư ký khuôn chặt | **Model on-device** (macOS 26+) | CHỈ gán nhãn cố định + trích xuất theo schema |

⚠️ **Model on-device nhỏ (~3B) — hai điều cấm, đo thật 31/07/2026 trên M1 8GB:**
hỏi tự do thì nó *diễn vai gọi tool* rồi dừng thay vì trả lời; và tính tiền nhiều bước
thì **sai gấp 10 lần** trong khi trình bày rất mạch lạc. Chất lượng tỉ lệ thuận với độ
chặt của khuôn — có schema thì tốt, thả tự do thì thành rác.

## Bảng chia việc theo loại task

| Loại task | Maker | Checker | Ghi chú |
|---|---|---|---|
| Code mới / refactor | Claude host | Codex | Codex review adversarial |
| Review code | Codex | — | Lane số 1 |
| Audit số liệu / văn bản | Codex | Claude + validator | Nhớ gate câu-hỏi |
| Prose/classify/OCR bulk | agy (hoặc Gemini CLI) | Claude spot-check | Value lane |
| OCR batch >50 / classify volume | OpenRouter free | Validator + spot-check | 1K RPD |
| Gán nhãn cố định / trích xuất schema | Model on-device | Validator | 0đ, không rời máy |
| Second opinion / debate | Grok | — | Không dùng một mình |
| Việc có dữ liệu thật | Claude host + lane cục bộ | Claude host | Không dispatch |
| Orchestrate / tổng hợp | Claude host | người | — |

## Luật "vendor cố định không được ngồi chơi"

Lane trả phí cố định (agy, Codex, Grok) mà cả tuần 0 lượt = đang đốt tiền. Đếm bằng
chính log của PolyKit — cột `served_model` là model **chạy thật**, khác cột `model` đã gọi:

```
python3 -c "
import json,collections,datetime,pathlib
from lib.paths import user_state_dir   # hoặc trỏ thẳng tới dispatch-log.jsonl
p=pathlib.Path(user_state_dir('polykit'))/'dispatch-log.jsonl'
cut=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=7)).isoformat()
c=collections.Counter(json.loads(l)['vendor'] for l in p.read_text().splitlines() if json.loads(l)['ts']>=cut)
print(c)"
```

## Quy trình dispatch 1 task (chuẩn)

1. Viết task: `objective, expected_output, timeout` (contract P4) + **liệt kê chỗ rẽ đã có đáp án**.
2. Kiểm PII → khử định danh nếu cần.
3. `/polykit:dispatch <vendor> -- <task>` (model để auto trừ khi có lý do ghim).
4. Nhận result JSON → chạy validator (nếu là số liệu/code) → checker khác vendor review.
5. Kết quả + bài học (nếu có) ghi về artifact của dự án — không để trong chat.

## Tham khảo máy-riêng (tùy chọn, không bắt buộc để dùng PolyKit)
- Bench nội bộ & traits: `~/Claude/CHEATSHEETS/vendor-intelligence/` + plugin model-intelligence.
- Routing digest: `~/.claude/rules/routing-summary.md`.
