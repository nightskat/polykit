| Việc | Trạng thái | Lệnh kiểm chứng | Kết quả / Output nguyên văn |
|---|---|---|---|
| Sửa test | Xong | `~/.pyenv/versions/3.11.8/bin/python -m pytest tests/` | `============================= 152 passed in 9.44s ==============================` (exit 0) |
| Revert vòng 6 | Đỏ | `~/.pyenv/versions/3.11.8/bin/python -m pytest tests/test_vong6.py` | `FAILED ... AssertionError: Expected None, got claude-opus-5` (exit 1) |
| Failover cờ đúng | Xong | `python3 bin/failover.py --pressure 85 --dry-run` | `[DRY RUN] ⚠️ Claude còn ~15% (pressure 85%). Handoff sang đâu? codex / gemini / để cap` (exit 0) |
| Sửa lệnh 2b | Xong | `printf "prompt" \| python3 bin/dispatch.py agy auto --result-json` | `{"status": "ok", "vendor": "agy", "model": "gemini-3.7-flash-high", "summary": "agy completed successfully", ... "exit_code": 0, "served_model": "gemini-3.7-flash-high"}` (exit 0) |
| Lệnh doctor | Xong | `python3 bin/doctor.py` | (In ra bảng VENDOR/STATE/PATH) (exit 0) |
| Lệnh watcher | Xong | `python3 bin/watcher.py --dry-run` | `[DRY RUN] 🔔 polykit: agy ready→auth_unverified; agy -14 models` (exit 0) |

## 7 tên `--dump-config` (chạy vòng lặp bash)
Lệnh: `for v in agy dsh grok codex gemini claude openrouter; do python3 bin/dispatch.py $v --dump-config 2>/dev/null | python3 -c 'import sys, json; print(json.dumps(json.load(sys.stdin)))'; done`
```json
{"vendor": "agy", "requested_model": "auto", "resolved_model": "gemini-3.7-flash-high", "default_model": "gemini-3.7-flash-high", "traps_count": 6}
{"vendor": "dsh", "requested_model": "auto", "resolved_model": "deepseek-v4-pro", "default_model": "deepseek-v4-flash", "traps_count": 5}
{"vendor": "grok", "requested_model": "auto", "resolved_model": "grok-4.6", "default_model": "grok-4.6", "traps_count": 2}
{"vendor": "codex", "requested_model": "auto", "resolved_model": "gpt-5.6-terra", "default_model": "gpt-5.6-terra", "traps_count": 5}
{"vendor": "gemini", "requested_model": "auto", "resolved_model": "auto", "default_model": null, "traps_count": 2}
{"vendor": "claude", "requested_model": "auto", "resolved_model": "claude-opus-5", "default_model": "claude-opus-5", "traps_count": 1}
{"vendor": "openrouter", "requested_model": "auto", "resolved_model": "auto", "default_model": null, "traps_count": 0}
```
(Tất cả trả về exit 0)
