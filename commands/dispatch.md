---
description: Dispatch task tới vendor (agy|dsh|codex|gemini|claude|grok|openrouter), degrade nếu thiếu
argument-hint: "<vendor> [model] -- <prompt>"
allowed-tools: Bash
---
Parse `$ARGUMENTS`: token đầu = vendor, phần sau `--` = prompt (mặc định model=auto).
`--timeout` mặc định 120s, **trần cứng 600s** — truyền cao hơn bị chặn ngay ở cổng validate
(`ERROR: dispatch blocked: timeout must be a positive integer 1-600`), không chạy vendor.
Chạy, prompt qua stdin, in kết quả JSON:
```
echo "<prompt>" | python3 "${CLAUDE_PLUGIN_ROOT}/bin/dispatch.py" <vendor> [model] --result-json
```
