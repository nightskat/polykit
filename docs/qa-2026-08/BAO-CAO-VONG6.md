# Báo cáo Vòng 6

| Yêu cầu | Lệnh + Kết quả (Exit code) |
|---|---|
| Nhánh **lỗi** | `FAKE_OC_FAIL=1 PATH="/tmp/pk-fakebin:$PATH" python bin/dispatch.py opencode --no-traps --result-json --allow-unknown-model` → `"status": "error", "served_model": null` và có `"warnings": ["boom: fake fail", "vendor 'opencode' không nhận cờ..."]` **(Exit 1)** |
| Nhánh **quota** | `FAKE_OC_QUOTA=1 PATH="/tmp/pk-fakebin:$PATH" python bin/dispatch.py opencode --no-traps --result-json --allow-unknown-model` → `"status": "skipped", "reason": "quota_capped", "served_model": null` **(Exit 1)** |
| Nhánh **ok** | `PATH="/tmp/pk-fakebin:$PATH" python bin/dispatch.py opencode --no-traps --result-json --allow-unknown-model` → `"status": "ok", "served_model": null` và có cảnh báo trong mảng warnings **(Exit 0)** |
| Vendor **có** cờ (dsh) | `python bin/dispatch.py dsh --no-traps --result-json` → `"served_model": "deepseek-v4-pro", "warnings": []` **(Exit 0)** |
| **Chế độ text** (stderr) | `PATH="/tmp/pk-fakebin:$PATH" python bin/dispatch.py opencode --no-traps --allow-unknown-model` → stderr in `[polykit] warning: vendor 'opencode' không nhận cờ model...` stdout: `fake ok output` **(Exit 0)** |
| `pytest tests/ -q` | `151 passed in 10.83s` **(Exit 0)** |
| Revert (Đỏ) | Hoàn nguyên vá: `pytest tests/test_vong6.py -q` → `3 failed, 1 passed in 0.42s`. (Fail ở `Expected None, got qwen/qwen3.7-flash` và không có warning ở stderr) |
| Vá lại (Xanh) | `pytest tests/test_vong6.py -q` → `4 passed` / `151 passed` tổng thể |
| 11 tên `--dump-config` | `for v in agy dsh grok codex gemini claude opencode goose zeroclaw jules openrouter; do python bin/dispatch.py $v --dump-config >/dev/null && echo "$v: exit 0"; done` → Toàn bộ 11 vendor in `exit 0`. |
