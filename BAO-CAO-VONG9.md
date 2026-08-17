| Yêu cầu | Lệnh / Output chứng minh (Dán nguyên văn) |
|---|---|
| `build_claude_cmd` (Lỗi 1) | `['claude', '--model', 'claude-opus-5', '--effort', 'low', '--no-session-persistence', '--disable-slash-commands', '--tools', '', '--permission-mode', 'plan', '-p', 'hi']` |
| `dispatch.py claude` giả (Lỗi 1) | `{"status": "ok", "vendor": "claude", "model": "claude-opus-5", "summary": "claude completed successfully", "warnings": [], "stdout": "", "exit_code": 0, "reason": null, "served_model": "claude-opus-5"}` |
| Vendor thật sự không nhận cờ (Lỗi 1) | `{"status": "ok", "vendor": "fakegrok", "model": "fake-4.6", "summary": "fakegrok completed successfully", "warnings": ["vendor 'fakegrok' không nhận cờ model, đang chạy mặc định của chính nó, không xác định được slug."], "stdout": "ok", "exit_code": 0, "reason": null, "served_model": null}` |
| `failover.py` gửi thật (Lỗi 2) | `{"action": "ping_proactive", "signal": "pressure", "message": "⚠️ Claude còn ~15% (pressure 85%). Handoff sang đâu? codex / gemini / để cap", "notified": true}` |
| `failover.py --dry-run` (Lỗi 2) | `{"action": "ping_proactive", "signal": "pressure", "message": "⚠️ Claude còn ~15% (pressure 85%). Handoff sang đâu? codex / gemini / để cap", "notified": false, "dry_run": true}` |
| Không còn cờ `--send` (Lỗi 2) | Output của `grep -rn "send" commands/ README.md CLAUDE.md`: (Trống - exit code 1, đã xoá sạch) |
| Test `test_dynamic_vendor` (Lỗi 4) | Sử dụng `unittest.mock.patch` để tạo mock `vendors.json` nội tuyến không làm vỡ các vendor mặc định. |
| `$PY -m pytest tests/ -q` (Chạy test xanh) | `152 passed in 9.90s` |
| Phép revert lỗi 1 → test ĐỎ | `FAILED tests/test_vong6.py::test_vong6_ok_branch - AssertionError: Expected None, got claude-opus-5` |
