HỎNG 3 CHỖ
PY=`~/.pyenv/versions/3.11.8/bin/python` · `python` vẫn EXIT 127 · `bin/dispatch.py` (shebang) chạy được.

## Phát hiện mới — do bản vá đẻ (nặng → nhẹ)

| # | Mức | Lỗi | Lệnh + output thật + exit |
|---|---|---|---|
| 1 | 🔴 | `--doctor dsh` **không bao giờ OK** dù vendor sống. verify (đã có `--profile`) thành công 333 dòng; rồi tự ghép `dsh --dump-config` thiếu profile → EXIT 1. Workaround `vcmd == "dsh --dump-config"` là **mã chết**. | `bin/dispatch.py dsh --doctor` stderr: `running zero-quota \`--dump-config\`` + `error: --profile <name> is required` + `zero-quota cmd exited 1` **EXIT 1**. `dsh --profile headless --dump-config` trần **EXIT 0**. `dsh --dump-config` trần **EXIT 1**. `$PY -c` `vendor_verify_cmd("dsh")` = `'dsh --profile headless --dump-config'` · `== "dsh --dump-config"` → `False`. |
| 2 | 🟠 | Vendor JSON-only chưa cài → `status=error` exit 127, **không** `skipped/not_installed`. Vá thêm nhánh `else` nhưng bỏ probe. Phá P1. | `$PY` inject `fakeco` headless=`fakeco_xyz_not_installed_zz run '<prompt>'` rồi `run_vendor("fakeco","hello")` → `status=error reason=vendor_exit_nonzero exit_code=127` warnings=`/bin/sh: fakeco_xyz_not_installed_zz: command not found` |
| 3 | 🟠 | `served_model` bịa cho vendor JSON. | `printf hi \| $PY bin/dispatch.py opencode --no-traps --result-json` → `served_model=qwen/qwen3.7-flash (provider openrouter)` **EXIT 0**. JSON không có `model_flag` — lệnh không ghim model. |

## 4 lỗi vòng 1 — đã hết (cùng lệnh v1)

| Lỗi cũ | Lệnh | Kết quả nay |
|---|---|---|
| doctor OK giả | `$PY bin/dispatch.py agy --doctor` | hết `/bin/sh: /model`; `agy OK` **EXIT 0** |
| openrouter mất | `$PY bin/dispatch.py openrouter --dump-config` | **EXIT 0** `vendor=openrouter` |
| unknown_vendor | `printf hi \| $PY bin/dispatch.py opencode --no-traps --result-json` | `status=ok` (không unknown). goose/jules/zeroclaw → `missing_fields` **EXIT 1** |
| model bịa | `$PY bin/dispatch.py dsh totally-fake-model --dump-config` | **EXIT 2** `Valid models: deepseek-v4-pro, deepseek-v4-flash` |

## Lệnh trong BAO-CAO-VA-VONG2.md

| Lệnh | Đối chiếu |
|---|---|
| `bin/dispatch.py agy --doctor` | KHỚP (`agy OK` EXIT 0) |
| `bin/dispatch.py dsh --doctor` | KHỚP (họ khai EXIT 1 — đúng, đó là bug mới #1) |
| `bin/dispatch.py dsh --dump-config` | KHỚP `resolved_model=deepseek-v4-pro` EXIT 0 |
| `dsh totally-fake-model --dump-config` | KHỚP EXIT 2 |
| `git diff --quiet config/vendors.json; echo $?` | KHỚP `0` |
| `pytest tests/ -q` → 142 | KHỚP `$PY -m pytest tests/ -q` → `142 passed in 21.31s` **EXIT 0** |

## 5 yêu cầu spec

| # | Kết quả | Bằng chứng |
|---|---|---|
| 1 choices từ JSON | ✅ | bản sao + `fakeco` → 11 tên. File gốc không đổi. `--help` = 10 JSON + `openrouter` |
| 2 dsh ghim pro | ✅ | `dsh --dump-config` → `resolved_model=deepseek-v4-pro` **EXIT 0** |
| 3 auto, dsh ≠ flash | ✅ | dsh auto→pro. agy auto→`gemini-3.7-flash-high`. Không flash |
| 4 `--doctor` | ❌ dsh | grok/gemini/claude OK **EXIT 0**. dsh luôn **EXIT 1** (#1). goose/OR: không có verify **EXIT 1** |
| 5 traps → stderr | ✅ | `printf '' \| $PY bin/dispatch.py dsh --result-json 2>/dev/null` stdout JSON sạch, 0 chữ trap. stderr (không nuốt) 5 traps. `--no-traps` stderr rỗng. **EXIT 1** (prompt rỗng) |

## Ác ý (mã thoát thật)

| Ca | Exit | Output |
|---|---|---|
| vendor `khongco` | **2** | argparse `invalid choice` |
| model lạ dsh | **2** | `not in vendor 'dsh' valid models` |
| JSON hỏng (lib, bản sao) | exception | `JSONDecodeError: Expecting property name…` |
| thiếu `schema_version` | exception | `ValueError: schema_version != 2 (got None)` |
| thiếu key `vendors` | 0 (lib) | `vendor_names=[]` — không crash |
| `DEEPSEEK_API_KEY` cắt + `security` giả | **1** | `MISSING_CREDENTIAL` `status=error` |
| `--cd /tmp/pk-qa-no-such-dir-xyz` grok | **1** | `os error 2` |

Không ca nào chết im `exit 0`.

## Ràng buộc

| Check | Kết quả |
|---|---|
| `git diff --quiet config/vendors.json; echo $?` | **0** |
| dependency mới | Không. `requirements.txt` chỉ stdlib; vá thêm `shlex` (stdlib) |
| test cũ | **114 passed** EXIT 0. Cả bộ **142 passed** EXIT 0 |

Không sửa code / không sửa `vendors.json`.
