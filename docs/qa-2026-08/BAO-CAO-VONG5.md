# Báo Cáo Vòng 5

Đã hoàn thành các yêu cầu vá lỗi `served_model` và khoá hành vi bằng test.

## Lệnh đã chạy

### 1. opencode `served_model: null`
```
$ printf hi | ~/.pyenv/versions/3.11.8/bin/python bin/dispatch.py opencode --no-traps --result-json --timeout 20
[polykit] warning: model list for vendor 'opencode' is unknown, cannot validate 'qwen/qwen3.7-flash'
{
  "status": "ok",
  "vendor": "opencode",
  "model": "qwen/qwen3.7-flash",
  "summary": "opencode completed successfully",
  "warnings": [
    "vendor 'opencode' không nhận cờ model, đang chạy mặc định của chính nó, không xác định được slug."
  ],
  "stdout": "Hi! How can I help you today?\n",
  "exit_code": 0,
  "reason": null,
  "served_model": null
}
```

### 2. dsh `served_model` có giá trị
```
$ printf hi | ~/.pyenv/versions/3.11.8/bin/python bin/dispatch.py dsh deepseek-v4-flash --no-traps --result-json --timeout 20
{
  "status": "ok",
  "vendor": "dsh",
  "model": "deepseek-v4-flash",
  "summary": "dsh completed successfully",
  "warnings": [],
  "stdout": "Chào bạn! 👋\n\nTôi đang ở workspace `polykit` — repo Claude Code plugin gom multi-vendor CLI tooling (dispatch, quota failover, watcher). Theo CLAUDE.md thì v0.1 đã code hoàn chỉnh (6/6 milestone, 65 test pass).\n\nBạn muốn làm gì hôm nay? Ví dụ:\n- Chạy/test lại hệ thống (`bin/doctor.py`, pytest…)\n- Thêm tính năng mới hoặc fix bug\n- Review code, cập nhật SPEC/docs\n- Điều gì khác\n\nCứ nói tôi nghe! 😄\n",
  "exit_code": 0,
  "reason": null,
  "served_model": "deepseek-v4-flash"
}
```

### 3. pytest - số test >142
```
$ ~/.pyenv/versions/3.11.8/bin/python -m pytest tests/ -q
........................................................................ [ 48%]
........................................................................ [ 97%]
...                                                                      [100%]
147 passed in 11.99s
```

### 4. Tự làm phép thử revert nhánh `models is None`
**Revert exit 2:**
```
$ ~/.pyenv/versions/3.11.8/bin/python -m pytest tests/test_vong5.py -q
F...F                                                                    [100%]
=================================== FAILURES ===================================
___________ test_vendor_chua_biet_danh_sach_model_dump_config_exit_0 ___________

    def test_vendor_chua_biet_danh_sach_model_dump_config_exit_0():
...
>           assert res.returncode == 0, f"Expected 0 for {vendor}, got {res.returncode}. Stderr: {res.stderr}"
E           AssertionError: Expected 0 for claude, got 2. Stderr: [polykit] warning: model list for vendor 'claude' is unknown, cannot validate 'fake-model'
```

**Hoàn nguyên:**
```
$ ~/.pyenv/versions/3.11.8/bin/python -m pytest tests/test_vong5.py -q
.....                                                                    [100%]
5 passed in 0.58s
```
