---
description: Dispatch task tới vendor (codex|gemini|claude|grok|openrouter), degrade nếu thiếu
argument-hint: "<vendor> [model] -- <prompt>"
allowed-tools: Bash
---
Parse `$ARGUMENTS`: token đầu = vendor, phần sau `--` = prompt (mặc định model=auto).
Chạy, prompt qua stdin, in kết quả JSON:
```
echo "<prompt>" | python3 "${CLAUDE_PLUGIN_ROOT}/bin/dispatch.py" <vendor> [model] --result-json
```
