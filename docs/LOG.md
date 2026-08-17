# PolyKit — Nhật ký kỹ thuật

## 2026-08-14 — Doctor auth accuracy and Gemini Context7 dedupe

- `gemini --list-sessions` và `agy models` là probe phụ, không phải auth-status
  đáng tin cậy. Khi chúng thất bại không có dấu hiệu logout, doctor trả
  `auth_unverified`, không hướng dẫn login lại sai.
- Giữ phân loại `installed_not_authed` khi stderr có tín hiệu auth rõ như
  `not logged in`; hết quota vẫn là `quota_capped`.
- Thêm regression test; toàn bộ suite: `114 passed`.
- Gemini CLI tải Context7 hai lần (extension + `~/.gemini/settings.json`) nên ghi
  `Tool ... already registered. Overwriting.` Đã giữ extension, bỏ MCP settings
  trùng, và tạo backup `settings.json.bak-before-context7-dedupe-20260814`.
- Startup diagnostics ngoài sandbox sau thay đổi: không còn duplicate-registration
  hay extension error. Lỗi daily quota Gemini là hạn mức model, không phải plugin.

