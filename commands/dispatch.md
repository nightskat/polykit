---
description: Dispatch task tới vendor (agy|dsh|codex|gemini|claude|grok|openrouter), degrade nếu thiếu
argument-hint: "<vendor> [model] -- <prompt>"
allowed-tools: Bash
---
Parse `$ARGUMENTS`: token đầu = vendor, phần sau `--` = prompt (mặc định model=auto).
`--timeout` mặc định 120s, **trần cứng 600s** — truyền cao hơn bị chặn ngay ở cổng validate
(`ERROR: dispatch blocked: timeout must be a positive integer 1-600`), không chạy vendor.

## Prompt NGẮN, một dòng → stdin
```
echo "<prompt>" | python3 "${CLAUDE_PLUGIN_ROOT}/bin/dispatch.py" <vendor> [model] --result-json
```

## Prompt DÀI / nhiều dòng / có dấu tiếng Việt → `--prompt-file`
`echo "..."` **vỡ** với prompt dài: quoting, xuống dòng và dấu tiếng Việt hỏng ở tầng shell
trước khi tới dispatch. Ghi ra file rồi truyền đường dẫn:
```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/dispatch.py" <vendor> [model] --prompt-file <path> --result-json
```
File không đọc được hoặc rỗng → exit 2, chặn trước khi gọi vendor.

## Đọc kết quả
Nguồn chính thức là `--result-json`: `status`, `served_model`, `exit_code`, `warnings`.
Dòng `[polykit] served: <model>` chỉ ra stderr **khi model thật KHÁC model đã yêu cầu**
(router OpenRouter, lane `agy`, `gemini auto`). Trùng nhau thì im lặng — đó là **hành vi đúng**,
không phải lỗi mất dấu vết.

⚠️ Mã thoát của vendor CLI không đáng tin. Nghiệm thu bằng nội dung/kích thước kết quả,
và bằng **dấu vết phụ** (file nó bảo đã ghi có thật không, chạy lại có ra đúng số không).

## 🐞 Thấy bug thì phải GHI LẠI — không được nuốt
Agent nào dùng PolyKit mà gặp hành vi sai (vendor chết mà exit 0, cờ không có tác dụng,
tài liệu mô tả sai, prompt bị nuốt…) thì **bắt buộc**:

1. **Ghi ngay** vào `docs/BUGS.md` của repo PolyKit — một mục có: ngày, lệnh đã chạy nguyên văn,
   cái đã đo được (không phải cái đoán), và việc cần làm.
2. **Sửa luôn nếu sửa được trong phiên** rồi ghi kèm bằng chứng đã sửa (test hoặc live test).
   Không sửa được thì để nguyên mục đó ở trạng thái MỞ, đừng đóng khống.
3. **Đừng để file bug nằm untracked** — đã xảy ra 18/08: bug ghi xong nằm ngoài git suốt một ngày,
   không ai thấy, bản cài và repo tách nhau lúc nào không biết.

Trước khi ghi bug mới, đọc `docs/BUGS.md` xem đã có chưa.
