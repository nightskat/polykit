# BAO-CAO-DISPATCH-V2

## Thay đổi

| File | Gì |
|---|---|
| `bin/lib/vendor_config.py` | MỚI. Load `config/vendors.json` v2, expose vendor_names/default_model/traps/verify_cmd |
| `bin/dispatch.py` | Bỏ hard-code choices=[6 vendor]. Choices sinh từ JSON (10 vendor). Thêm --doctor, --no-traps, --dump-config. Auto→default_model |
| `bin/lib/dispatch_core.py` | Thêm build_dsh_cmd, write_dsh_patch, DSH_DEFAULT_MODEL=deepseek-v4-pro |
| `bin/lib/dispatcher.py` | Thêm lane dsh — patch YAML + Keychain inject + auto→pro |
| `bin/lib/vendors.py` | Thêm dsh vào REGISTRY |
| `tests/test_dispatch_v2.py` | 23 test mới |

## Quyết định thiết kế
1. dsh auto → pro: JSON ghi default=flash nhưng flash trả rỗng 2 lần → DSH_DEFAULT_MODEL override cứng = deepseek-v4-pro
2. dsh --model không tồn tại: viết file YAML patch tạm → `--patch <file>`, xóa sau
3. DEEPSEEK_API_KEY: inject từ macOS Keychain qua `security` nếu chưa có env
4. Traps in ra stderr trước dispatch, --no-traps để tắt
5. CHUA_KIEM: vendor có default_model="CHUA_KIEM" → coi None, auto giữ nguyên

## Lệnh đã chạy

### 1. Baseline test
```
$ ~/.pyenv/versions/3.11.8/bin/python -m pytest tests/ -q
114 passed in 11.32s
EXIT: 0
```

### 2. Test sau sửa
```
$ ~/.pyenv/versions/3.11.8/bin/python -m pytest tests/ -q
137 passed in 2.40s
EXIT: 0
```

### 3. Dispatch dsh --dump-config (0 token, chứng minh ghim đúng pro)
```
$ python bin/dispatch.py dsh --dump-config
{
  "vendor": "dsh",
  "requested_model": "auto",
  "resolved_model": "deepseek-v4-pro",
  "default_model": "deepseek-v4-flash",
  "traps_count": 5
}
EXIT: 0
```

### 4. Dispatch dsh thật (echo "test" | ... --result-json)
```
$ echo "test" | python bin/dispatch.py dsh --result-json
STDOUT: {"status": "ok", "vendor": "dsh", "model": "deepseek-v4-pro", ...}
STDERR: [polykit] ⚠ traps for dsh: (5 traps in ra stderr)
EXIT: 0
```

### 5. --doctor dsh
```
$ python bin/dispatch.py dsh --doctor
[polykit] doctor: running `dsh --profile headless --dump-config` ...
(full dsh config YAML đổ ra stdout — 180+ dòng config plugin)
[polykit] doctor: dsh OK
EXIT: 0
```

### 6. --doctor agy
```
$ python bin/dispatch.py agy --doctor
[polykit] doctor: running `agy -p "/model"` ...
gemini-3.7-flash-high	Gemini 3.7 Flash (High)
[polykit] doctor: agy OK
EXIT: 0
```

## Không sửa
- `config/vendors.json` — chỉ đọc
- Không thêm dependency ngoài stdlib
