---
description: Quota failover — pressure→ping trước, cap→ping reactive, lỗi lạ→im
argument-hint: "[--pressure N | --stderr-file PATH] (luôn chạy --dry-run, không gửi thật)"
allowed-tools: Bash
---
Plugin luôn truyền `--dry-run` để chỉ in ra, KHÔNG gửi Telegram:
```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/failover.py" --dry-run $ARGUMENTS
```
