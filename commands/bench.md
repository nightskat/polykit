---
description: Bench tổng hợp 5 task có đáp án, so sánh vendor/model/effort
allowed-tools: Bash
argument-hint: --runs N [--output-dir PATH] vendor:model:effort [...]
---
Chạy và hiển thị nguyên văn output (chỉ dùng dữ liệu tổng hợp cố định):
```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/bench_main.py" $ARGUMENTS
```
Không đọc key từ file; API key phải có trong env của tiến trình.

DeepSeek API: dùng `deepseek:deepseek-flash:low` (effort: `low|high|max`).
Có thể bỏ model: `deepseek::high` dùng mặc định `deepseek-flash`.
Slug `deepseek-v4.1-flash` trả HTTP 400 trên DeepSeek API theo lần chạy 04/11;
profile Go/Hermes có namespace riêng và không đổi theo slug API này.
Kết quả giữ tối đa 4000 ký tự cuối của câu trả lời. Lỗi quota agy được ghi
`err=quota`, không tính là đáp án sai.
