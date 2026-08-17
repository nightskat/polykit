# DAP-VONG2
HỎNG 6 CHỖ — `git diff --quiet config/vendors.json; echo $?` in **1** (không phải 0). Maker vòng 2 `exit=0` lúc 13:10 nhưng **không vá**: không có `BAO-CAO-VA-VONG2.md`, mtime code 11:58 < đề bài 13:09. 4 lỗi «đã vá» còn nguyên.

PY=`~/.pyenv/versions/3.11.8/bin/python` (`python` = EXIT 127).

## (a) 4 lỗi vòng 1 — còn / hết

| # | Lỗi | | Lệnh + output thật + exit |
|---|---|---|---|
| 1 | `--doctor` OK giả | **CÒN** | `$PY bin/dispatch.py agy --doctor` stderr: `running zero-quota \`/model\`` + `/bin/sh: /model: No such file` + `/usage` tương tự rồi `doctor: agy OK` **EXIT 0**. `$PY bin/dispatch.py dsh --doctor` verify_cmd ok rồi `error: --profile <name> is required` ×2 (`--dump-config`, `--dump-default-config`) rồi `doctor: dsh OK` **EXIT 0**. Code `except Exception: pass` + không đọc returncode zq. |
| 2 | `openrouter` mất CLI | **CÒN** | `$PY bin/dispatch.py openrouter --dump-config` → `invalid choice: 'openrouter'` (choices 10 tên JSON, không OR) **EXIT 2** |
| 3 | vendor JSON → `unknown_vendor` | **CÒN** | `printf hi \| $PY bin/dispatch.py opencode --no-traps --result-json` → `status=blocked reason=unknown_vendor` **EXIT 1**. goose/jules/zeroclaw cùng if/elif+REGISTRY. |
| 4 | model bịa vẫn nhận | **CÒN** | `$PY bin/dispatch.py dsh totally-fake-model --dump-config` → `resolved_model: totally-fake-model` **EXIT 0**. `$PY bin/dispatch.py dsh --allow-unknown-model --dump-config` → `unrecognized arguments` **EXIT 2**. Không có cờ, không reject. |

## (b) Lỗi MỚI (không trùng 4 cái trên)

| # | Mức | Lỗi | Lệnh + output + exit |
|---|---|---|---|
| 5 | 🔴 | `--dump-config` **EXIT 0** cho vendor không dispatch được — nhìn như cấu hình ổn. | `$PY bin/dispatch.py {opencode,goose,jules,zeroclaw} --dump-config` cả 4 **EXIT 0** (opencode `resolved_model=qwen/qwen3.7-flash (provider openrouter)`). Cùng vendor lúc chạy thật = #3 EXIT 1. |
| 6 | 🟠 | `--doctor dsh` in model live = **flash** (YAML dòng `model: deepseek-v4-flash`). Spec bắt in «model đang chạy»; flash trên task nhiều bước = lỗi nặng. Dispatch auto thì ghim pro. | `$PY bin/dispatch.py dsh --doctor` stdout 333 dòng, dòng 44 `model: deepseek-v4-flash` rồi vẫn `doctor: dsh OK` **EXIT 0**. `$PY bin/dispatch.py dsh --dump-config` `resolved_model=deepseek-v4-pro` **EXIT 0**. |

## Đối chiếu «Lệnh đã chạy»

| # | Nguồn | Kết quả |
|---|---|---|
| — | `BAO-CAO-VA-VONG2.md` | **KHÔNG CHẠY ĐƯỢC** — `ls` → `No such file` EXIT 1. Maker `.maker2.out` 6 dòng đọc file, 0 lệnh, 0 vá. |
| 1–2 | maker v1 pytest | **KHỚP** `$PY -m pytest tests/ -q` → **137 passed in 7.73s EXIT 0**. Cũ `--ignore=test_dispatch_v2` → **114 passed EXIT 0**. 0 test mới cho 4 lỗi (spec vòng 2 bắt mỗi lỗi ≥1 test). |
| 3–6 | maker v1 `python bin/dispatch.py …` | **KHÔNG CHẠY ĐƯỢC** `python …` → `pyenv: python: command not found` **EXIT 127**. Qua PY: dump-config dsh **KHỚP** pro EXIT 0; `--doctor` dsh/agy **LỆCH** (vẫn OK giả, xem #1). |

## 5 yêu cầu spec gốc

| # | Kết quả | Bằng chứng |
|---|---|---|
| 1 choices từ JSON | ⚠️ nửa | Bản sao + `fakeco` → `vendor_names` 11 tên có `fakeco`. CLI không trỏ file khác. Dispatch vẫn if/elif → #3. |
| 2 dsh ghim pro | ✅ dump-config | `$PY bin/dispatch.py dsh --dump-config` `resolved_model=deepseek-v4-pro` **EXIT 0** (0 token). |
| 3 auto ≠ flash | ✅ CLI | `dsh auto` → pro. `agy auto` → `gemini-3.7-flash-high`. |
| 4 `--doctor` | ❌ | Chạy 5 vendor: grok/gemini/claude OK thật EXIT 0; agy/dsh OK giả EXIT 0 (#1); goose `không có verify_cmd` **EXIT 1**. |
| 5 traps → stderr | ✅ | `printf '' \| $PY bin/dispatch.py dsh --result-json 2>/dev/null` stdout = JSON `blocked` sạch. stderr (không nuốt) 5 traps. `--no-traps` stderr rỗng. **EXIT 1** (prompt rỗng). |

## Ác ý (mã thoát thật)

| Ca | Exit | Output |
|---|---|---|
| vendor `khongco` | **2** | argparse `invalid choice` — không im |
| model lạ dsh | **0** | dump-config nhận slug — #4 |
| JSON hỏng (lib, bản sao) | exception | `JSONDecodeError: Expecting property name…` (CLI không bắt) |
| thiếu `schema_version` | exception | `ValueError: schema_version != 2 (got None)` |
| thiếu key `vendors` | **0** | `vendor_names=[]` — không crash |
| `DEEPSEEK_API_KEY` cắt + `security` giả | **1** | `MISSING_CREDENTIAL` `status=error` — không im |
| `--cd /tmp/pk-qa-no-such-dir` grok | **1** | `Failed to set working directory… os error 2` |

## Ràng buộc

| Check | Kết quả |
|---|---|
| `git diff --quiet config/vendors.json; echo $?` | **1** — không trống (v1→v2, `+174/-7`). mtime JSON 11:49 < vòng 2 13:09 → maker vòng 2 **không đụng**, nhưng lệnh bắt buộc thất bại. |
| dependency mới | Không. `requirements.txt` stdlib; import = json/pathlib/functools/tempfile. |
| test cũ | **114 passed EXIT 0**. Test 4 lỗi vá: **không có**. |

Không sửa code / không sửa `vendors.json`.
