# Báo cáo Vòng 10

## HÀNH VI ĐÃ ĐỔI
- Trả về `served_model=model` (thay vì `None` như cũ) khi vendor không ở trạng thái sẵn sàng (not_installed, quota_capped, v.v.) ngoại trừ khi `model="auto"`. Việc này để đảm bảo nhất quán giữa 4 nhánh kết quả (`ok/error/quota/not_installed`), tránh làm rỗng `served_model` một cách sai lệch khi lỗi xuất hiện trước khi gọi API thật.

## Lỗi 1: `/polykit:failover` Gửi Telegram Thật
- **Nguyên nhân**: Lệnh trong `commands/failover.md` đã bị cắt `--dry-run`, khiến lệnh gọi chạy thật và gửi cảnh báo đến Telegram.
- **Sửa chữa**: 
  - Hoàn nguyên `--dry-run` vào `commands/failover.md` để đảm bảo an toàn.
  - Sửa đổi tài liệu ở `README.md`, `CLAUDE.md`, và `commands/failover.md` để loại bỏ các trích dẫn sai về việc "gửi thật" hay `--send`.

## Lỗi 2: Test "không nhận cờ model" RỖNG RUỘT
- **Nguyên nhân**: `test_lenh_khong_ghim_duoc_model` bị bẻ gọi trực tiếp hàm nội bộ `run_vendor(model="auto")`, hoàn toàn vượt mặt CLI flow và không chứng minh được gì.
- **Sửa chữa**:
  - Dựng lại test sử dụng mock `sys.argv` và patch `sys.stdin.read` để mô phỏng một lần gọi CLI qua `dispatch.main()`.
  - Tạo `fakevendor` trong fixture mock với `model_flag: null`, chứng minh luồng CLI thực sự bắt được trường hợp vendor thiếu cờ, in cảnh báo, và xuất ra JSON với `served_model: null`.
  - Phép revert chứng minh nếu bẻ dòng logic xử lý trong `dispatcher.py` thì test sẽ đỏ ngay lập tức.

## Lỗi 3: `claude` sót nhánh `not_installed`
- **Nguyên nhân**: Mặc dù các nhánh ok/error/quota đã có `served_model` đúng, nhưng nhánh skip (trong đó có `not_installed` hay trạng thái đầu vào không READY) lại hardcode trả về `served_model=None`.
- **Sửa chữa**:
  - Cập nhật hàm `run_vendor` trong `dispatcher.py`: các trường hợp skip do detector trả về hoặc thiếu binary đều sẽ trả về `served_model=model` (hoặc `None` nếu `model="auto"`).
  - Cập nhật test `test_vong6_not_installed_branch` để kiểm tra điều kiện này đúng.

## CHỨNG MINH
```bash
# 1. grep dry-run
$ grep -n "dry-run" commands/failover.md
3:argument-hint: "[--pressure N | --stderr-file PATH] (luôn chạy --dry-run, không gửi thật)"
6:Plugin luôn truyền `--dry-run` để chỉ in ra, KHÔNG gửi Telegram:
8:python3 "${CLAUDE_PLUGIN_ROOT}/bin/failover.py" --dry-run $ARGUMENTS

# 2. Notifier giả
$ cat << 'EOF' > /tmp/fake.sh
#!/bin/bash
echo "notified: true"
echo "CALLED args=$1"
EOF
$ chmod +x /tmp/fake.sh
$ POLYKIT_NOTIFIER=/tmp/fake.sh ~/.pyenv/versions/3.11.8/bin/python bin/failover.py --pressure 85
{"action": "ping_proactive", "signal": "pressure", "message": "⚠️ Claude còn ~15% (pressure 85%). Handoff sang đâu? codex / gemini / để cap", "notified": true}
$ POLYKIT_NOTIFIER=/tmp/fake.sh ~/.pyenv/versions/3.11.8/bin/python bin/failover.py --pressure 85 --dry-run
[DRY RUN] ⚠️ Claude còn ~15% (pressure 85%). Handoff sang đâu? codex / gemini / để cap
{"action": "ping_proactive", "signal": "pressure", "message": "⚠️ Claude còn ~15% (pressure 85%). Handoff sang đâu? codex / gemini / để cap", "notified": false, "dry_run": true}

# 3. grep send
$ grep -rn "send" README.md commands/ CLAUDE.md
# (exit code 1 - không tìm thấy kết quả nào)

# 4. Test suite pytest
$ ~/.pyenv/versions/3.11.8/bin/python -m pytest tests/ -q
........................................................................ [ 47%]
........................................................................ [ 94%]
........                                                                 [100%]
152 passed in 7.95s
```
