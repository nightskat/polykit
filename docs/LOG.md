# PolyKit — Nhật ký kỹ thuật

## 2026-11-03 (chiều) — Sửa bug còn mở trên nền PR #1 + #2

**Đã làm**
- Gộp `ci/three-os` (PR #2) + `claude/vigilant-johnson-wb7bbe` (PR #1) vào branch từ main; không xung đột; 1081 pass ngay sau merge (local Linux).
- QUAN SÁT-4: exit 0 + stdout rỗng → `error`/`empty_output` (trước: `ok`). `--expect-artifact` gỡ về ok để artifact quyết định.
- BUG-20: gate output_dir/symlink PDF chạy TRƯỚC kiểm `pdftoppm`.
- BUG-14 (Agy/DSH): đóng theo test BUG-13/15 có sẵn; timestamp `ready` → BACKLOG.
- `tests/fake_cli.install_python_shim`: vendor giả Python + `.cmd` trên Windows; bỏ skip win32 của `test_vong6`.
- BUG-21 (lộ ra khi CI Windows chạy test PR #1): lane argv không tìm `.cmd` (PATHEXT) + `--doctor` chạy `shell=True` với nháy POSIX. Sửa `resolve_argv0` + `shlex.split`.
- Smoke máy sạch: thêm `USERPROFILE`/`SystemRoot` trên Windows; CI in test đỏ (`-rfE`).
- Review advisor: exit 0 + stdout rỗng + stderr quota → `quota_capped` (không phải `empty_output`).
- CI Windows qua các vòng: 25 đỏ → 6 đỏ → xanh. Run #13 (`213aca9`): ubuntu/macos/windows đều success; windows 1094 pass/2 skip (đọc dòng tổng trong log). Local Linux HEAD: 1096 pass/1 skip.

**Bài học**
- Banner `traps for agy` là của PolyKit, ghi ra STDERR (`bin/dispatch.py:410`) — "stdout chỉ có banner" 20/08 thực chất là stdout rỗng; check rỗng bắt đúng ca đó.
- PR #1 merge sau PR #2 nên test subprocess của nó (agy giả shebang) chưa từng chạy trên Windows.

**Phát hiện**
- Nhánh adapter generic (vendor tự khai trong vendors.json) vẫn dựng lệnh shell bằng `shlex.quote` (`bin/lib/dispatcher.py` ~1140) — nháy POSIX, có thể sai với cmd.exe. CHƯA KIỂM bằng test Windows.
- Gọi `.cmd` qua argv vẫn đi qua cmd.exe ⇒ prompt có `&|%` có thể bị diễn giải. CHƯA KIỂM.
- BUG-6 (grok) và QUAN SÁT-3 (text PII) vẫn MỞ: cần vendor/pg-redact thật, không sửa bằng fixture được.

**Lệnh chạy lại**
```
python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q -rs
```

## 2026-11-03 — CI 3 OS (ubuntu / macos / windows)

**Đã làm**
- Thêm `.github/workflows/tests.yml`: pytest, Python 3.11, matrix 3 OS, `fail-fast: false`, không secret, không gọi vendor thật.
- Thêm `requirements-dev.txt` (pytest, pillow, openpyxl) — runtime vẫn stdlib-only.
- Fixture `hermetic_vendors` (tests/conftest.py): `shutil.which` giả + `OPENROUTER_API_KEY` giả cho 10 test vốn mock runner nhưng vẫn đọc binary/key THẬT.
- Sửa code `bin/lib/vision.py` `SingleTurnConfirmation.is_valid_for`: chuẩn hoá `exact_files` cùng hàm với `files`.
- Test so path POSIX cứng → so `Path(...).resolve()` / `is_absolute()`.
- `test_vong6.py`: PATH dùng `os.pathsep`; skip trên win32 (fixture là bash script).
- Kết quả run #3: ubuntu 1045 pass/1 skip · macos xanh · windows 1039 pass/7 skip.

**Bài học**
- "Xanh trên máy dev" ≠ hermetic: 8 test chỉ xanh vì máy có `agy`/`gemini`/key OpenRouter; 2 test chỉ xanh vì có `pdftoppm`; 2 module test cần pillow/openpyxl mà requirements không ghi.
- Windows lộ chỗ code chuẩn hoá path một phía (`Path("/tmp/a.png")` → `\tmp\a.png`).

**Phát hiện**
- `vision._convert_pdf_to_images` kiểm thiếu `pdftoppm` TRƯỚC gate output_dir/symlink → máy không có pdftoppm thì gate an ninh không được thực thi (vẫn fail-closed nên không rò). CHƯA KIỂM có nên đổi thứ tự hay không.
- Fake vendor bằng bash script không chạy trên Windows → nhánh ok/error/quota của dispatch CLI (test_vong6) CHƯA KIỂM trên Windows. Cần fixture fake vendor bằng Python (`.cmd` wrapper) nếu muốn phủ.
- Số pass/skip macos lấy từ trạng thái job (success), CHƯA đọc dòng tổng trong log.

**Lệnh chạy lại**
```
python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q -rs
```

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


## 2026-11-02 — Tận dụng credit CCC + GCP (phiên "Free Cloud")
- Rà Mac 5 vendor song song (Hermes: deepseek, glm, codex, grok + agy riêng) ~6 phút, cả 5 nộp báo cáo; bẫy + brief mẫu ghi ở GUIDE §3.
- CCC hôm nay ~9 session: merge vi-textmatch#1, youtube-meo#65 #66, docshift-core#26 #27, audit-translator#95; còn mở polykit#1 (draft), so-cai#1 + #2 (merge theo thứ tự).
- Pilot Vertex AI Search: thua pg-hoi 20 điểm → giữ local; tài nguyên GCP đã xoá (bucket 404, engine/data store đã nhận lệnh xoá, chưa kiểm lại).
- Chốt của Tuan: tài nguyên không dư — có ích thì PHẢI dùng; đo trước rồi quyết.
