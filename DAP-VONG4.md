HỎNG 2 CHỖ
PY=`~/.pyenv/versions/3.11.8/bin/python` · `python` trần EXIT 127 · `pytest tests/ -q` → `142 passed in 13.64s` **EXIT 0** · `git diff --quiet config/vendors.json; echo $?` → **0** · 11/11 `--dump-config` **EXIT 0**.

## Phát hiện mới — do bản vá đẻ (nặng → nhẹ)

| # | Mức | Lỗi | Lệnh + output thật + exit |
|---|---|---|---|
| 1 | 🟠 | Vá «unknown-list → cho chạy» mở lại đường mặc định: `opencode` **không có `model_flag`**, lệnh không ghim model, nhưng `served_model` bịa = `default_model` (chuỗi mô tả, có cả `(provider openrouter)`). Evidence nói dối model đã chạy. | `printf hi \| $PY bin/dispatch.py opencode --no-traps --result-json --timeout 20` → warning `cannot validate 'qwen/qwen3.7-flash (provider openrouter)'` + `status=ok served_model=qwen/qwen3.7-flash (provider openrouter) stdout=Hi! How can I help you today?` **EXIT 0**. Mock `run_vendor`: `cmd=opencode run 'hello world' < /dev/null` · `model_flag_in_cmd=False` **EXIT 0**. PATH cắt: `served_model=null` `not_installed` **EXIT 1** (vá v3 còn). |
| 2 | 🟡 | Vá 2 lỗi v3 mà **0 test mới** (vẫn 142). Không khóa `claude --dump-config` EXIT 0, không khóa `models` dict. Revert nhánh `None` về exit 2 → pytest vẫn xanh — đúng kiểu lỗi 6/10 vendor chết vòng 3. | `rg 'cannot validate\|sai dạng' tests/` → **trống**. `test_dump_config_*` chỉ codex/dsh/openrouter. `test_reject_fake_model` chỉ `dsh`. |

## 2 lỗi vòng 3 — đã hết (cùng lệnh v3)

| Lỗi cũ | Lệnh | Nay |
|---|---|---|
| unknown-list chặn mọi slug | `$PY bin/dispatch.py claude --dump-config` | warning + JSON `resolved=claude-opus-5` **EXIT 0**. `claude claude-opus-5` **EXIT 0**. `opencode --dump-config` **EXIT 0**. `gemini gemini-2.5-pro` **EXIT 0**. `openrouter some-or-model` warning + JSON **EXIT 0**. |
| dict lọt im | `load_vendor_config(bản_sao)` dsh `models={...}` | `ValueError: vendor 'dsh' có trường 'models' sai dạng: dict`. str/int cùng.raise. |
| doctor dsh / agy trùng / codex 304KB | `--doctor` dsh/agy/codex | dsh **EXIT 0** stdout 21138B. agy `/model` rồi `/usage` **EXIT 0**. codex stdout **10319B**, 0 chữ `debug models` **EXIT 0**. |

## Lệnh trong BAO-CAO-VONG4.md

| Lệnh | Đối chiếu |
|---|---|
| for 11 vendor `--dump-config` EXIT 0 | **KHỚP** JSON từng vendor (kể cả `jules` `\u00f4ng`) |
| `dsh totally-fake --dump-config` EXIT 2 | **KHỚP** nguyên văn 3 dòng error |
| `claude abc --dump-config` EXIT 0 + warning | **KHỚP** |
| `$PY -c 'import vendor_config; vendor_config.load_vendor_config()'` (dsh dict) → ValueError | **LỆCH**: lệnh viết ra `ModuleNotFoundError: No module named 'vendor_config'` **EXIT 1**. Feature đúng khi `sys.path.insert(0,"bin")` + file tạm. |
| pytest `142 passed in 9.25s` | KHỚP 142/0 fail. **LỆCH thời gian** (thật `13.64s`; cổng `11.20s`) |

## 5 yêu cầu spec

| # | Kết quả | Bằng chứng |
|---|---|---|
| 1 choices từ JSON | ✅ | bản sao + `fakeco` → 11 tên. `--help` = 10 JSON + `openrouter` |
| 2 dsh ghim pro | ✅ | `dsh --dump-config` → `resolved_model=deepseek-v4-pro` **EXIT 0** |
| 3 auto ≠ flash (dsh) | ✅ | dsh auto→pro. agy auto→`gemini-3.7-flash-high`. `dsh flash` vẫn trong list, **EXIT 0** |
| 4 `--doctor` ≥3 | ✅ | dsh/codex/agy/grok/gemini/claude **EXIT 0**. goose/OR: không verify **EXIT 1** |
| 5 traps → stderr | ✅ | `printf '' \| $PY bin/dispatch.py dsh --result-json 2>/dev/null` stdout JSON sạch. stderr 5 traps. `--no-traps` stderr rỗng. **EXIT 1** (prompt rỗng). `claude --dump-config 2>/dev/null` JSON sạch. |

## Ác ý (mã thoát thật)

| Ca | Exit | Output |
|---|---|---|
| vendor `khongco` | **2** | argparse `invalid choice` |
| model lạ dsh / agy | **2** | `not in vendor '…' valid models` |
| slug lạ claude (chưa biết list) | **0** | warning stderr + dump JSON |
| JSON hỏng (lib, bản sao) | exception | `JSONDecodeError: Expecting property name…` |
| thiếu `schema_version` | exception | `ValueError: schema_version != 3 (got None)` |
| thiếu key `vendors` | 0 (lib) | `vendor_names=[]` — không crash |
| `models` dict/str/int (bản sao) | exception | `ValueError: … sai dạng: dict/str/int` |
| `--cd /tmp/pk-qa-no-such-dir-xyz` grok | **1** | `os error 2` `status=error` |
| `DEEPSEEK_API_KEY` cắt + `security` giả | **1** | `MISSING_CREDENTIAL` `status=error` — không im |

## Ràng buộc

| Check | Kết quả |
|---|---|
| JSON lược đồ ↔ reader | `schema_version=3`. Loader chặn non-list. Thiếu key `models` = unknown (warn, không chặn) — đúng spec v4. |
| dependency mới | Không. `requirements.txt` chỉ stdlib. |
| test | **142 passed 0 failed** EXIT 0. Không thêm test v4 → #2. |

Không sửa code / không sửa `vendors.json`.
