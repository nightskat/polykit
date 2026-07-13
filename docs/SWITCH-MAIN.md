# Playbook Chuyển Main Lane Khi Claude Cap

Khi Claude bị chạm hạn mức (cap), thực hiện 5 bước sau để chuyển lane mượt mà:

1. **Đọc Handoff Note**: Mở và đọc nội dung file `handoff-latest.md` được tự động tạo bởi hệ thống.
2. **Mở Codex Làm Main**: Chuyển session chính sang Codex bằng lệnh `codex`. Do Codex main không có context session dở từ Claude trước, handoff note sẽ bù đắp phần thông tin thiếu hụt này.
3. **Paste Handoff Note**: Dán nội dung handoff note vào session Codex để đồng bộ trạng thái công việc.
4. **Sử Dụng Worker**: Tiếp tục cấu hình Gemini hoặc Grok làm các worker phụ trợ thông qua `dispatch.py`.
5. **Quay Lại Claude**: Khi Claude hết hạn mức (reset), tạo handoff note từ Codex, paste ngược lại và quay về lane Claude.
