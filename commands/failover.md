---
description: Quota failover — pressure→ping trước, cap→ping reactive, lỗi lạ→im
argument-hint: "[--pressure N | --stderr-file PATH] (mặc định --dry-run, thêm --send để ping thật)"
allowed-tools: Bash
---
Mặc định chạy --dry-run (KHÔNG gửi Telegram). Nếu $ARGUMENTS có `--send` thì bỏ --dry-run:
```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/failover.py" --dry-run $ARGUMENTS
```
