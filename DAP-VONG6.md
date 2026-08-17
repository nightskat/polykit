HỎNG 1 CHỖ
PY=`~/.pyenv/versions/3.11.8/bin/python` · `pytest tests/ -q` → `151 passed in 11.34s` rồi `10.63s` **EXIT 0** · 11/11 `--dump-config` **EXIT 0** · `git diff --quiet config/vendors.json; echo $?` → `0`.

## Phát hiện mới — do bản vá đẻ (nặng → nhẹ)

| # | Mức | Lỗi | Lệnh + output thật + exit |
|---|---|---|---|
| 1 | 🟡 | Vá ghi warning ra stderr **trong `run_vendor`**, CLI text-error **in lại** `warnings[]`. Cùng một câu hiện 2 lần. `--result-json` không trùng (chỉ 1 dòng stderr). | `printf hi \| FAKE_OC_FAIL=1 PATH="/tmp/pk-fakebin:$PATH" $PY bin/dispatch.py opencode --no-traps --allow-unknown-model --timeout 5` stderr: `[polykit] warning: vendor 'opencode' không nhận cờ model…` rồi `ERROR: opencode failed…` rồi `Warnings:` / `  - boom: fake fail` / `  - vendor 'opencode' không nhận cờ model…` stdout trống **EXIT 1**. |

Chặn `served_model` **không** làm mất slug đúng: mock `dsh` `served_model=deepseek-v4-pro` + `--patch`. Live `printf 'say hi in 3 words' \| $PY bin/dispatch.py dsh --no-traps --result-json --timeout 40` → `status=ok model=served=deepseek-v4-pro warnings=[]` **EXIT 0**. Inject `model_flag=--model` vào opencode (cache, không sửa file): ok+error đều `served_model=qwen/qwen3.7-flash`. Timeout (cửa `except`) vẫn `served_model=None` — cửa cũ, không do vá này.

## 2 lỗi vòng 5 — đã hết

| Lỗi cũ | Lệnh | Nay |
|---|---|---|
| served_model bịa ở error/quota | Fake `/tmp/pk-fakebin/opencode` + `FAKE_OC_FAIL=1` / `FAKE_OC_QUOTA=1` / ok / `PATH=/usr/bin:/bin` | Cả 4 nhánh `served_model=null`. error **EXIT 1** + warning trong JSON+stderr. quota `status=skipped reason=quota_capped` **EXIT 1**. ok **EXIT 0**. not_installed **EXIT 1** (không có câu «không nhận cờ» — chưa chạy lệnh). Không `--allow-unknown-model` cũng null. |
| warning mất ở text | `printf hi \| PATH=fake $PY bin/dispatch.py opencode --no-traps --allow-unknown-model` | stderr có `[polykit] warning: vendor 'opencode' không nhận cờ model…` stdout=`fake ok output` **EXIT 0**. Có traps cũng còn. `2>/dev/null` stdout sạch. |

Revert **từng lỗi** rồi hoàn nguyên: lỗi 1 (`if status==ok`) → `2 failed, 2 passed in 0.37s` **EXIT 1**. lỗi 2 (cắt `stderr.write`) → `3 failed, 1 passed in 0.51s` **EXIT 1**. cả hai (HEAD) → `3 failed, 1 passed in 0.49s` **EXIT 1** (`Expected None, got qwen/qwen3.7-flash` + stderr trống). Restore `4 passed in 0.38s` / `151 passed`.

## Lệnh trong BAO-CAO-VONG6.md

| Lệnh họ ghi | Đối chiếu |
|---|---|
| Mọi dòng dùng `python bin/dispatch.py …` | **LỆCH / KHÔNG CHẠY ĐƯỢC**: `python` shim → `pyenv: python: command not found` **EXIT 127**. Spec đã dặn. Họ không dán lệnh thật (`$PY`). |
| `python … dsh --no-traps --result-json` (không pipe) → Exit 0 + `served_model=deepseek-v4-pro` | **LỆCH**. `$PY` + `</dev/null` → `status=blocked` Empty prompt `served_model=null` **EXIT 1**. Có pipe mới ra pro **EXIT 0**. |
| `python … opencode --no-traps --allow-unknown-model` (không pipe) → `fake ok output` Exit 0 | **LỆCH**. `$PY` + `</dev/null` → `ERROR: dispatch blocked: Empty prompt` **EXIT 1**. Có `printf hi` mới khớp. |
| pytest `151 passed in 10.83s` | **KHỚP 151**. **LỆCH thời gian** (`11.34s` / `10.63s`). Không kiểu gõ byte từ nhớ. |
| Revert `3 failed, 1 passed in 0.42s` / vá lại `4 passed` | **KHỚP số test**. Thời gian `0.49s`/`0.38s`. Họ revert **cả hai một lúc**, không từng lỗi — test vẫn đỏ đúng. |
| 11 tên dump-config exit 0 | **KHỚP** cả 11. dsh `resolved_model=deepseek-v4-pro` (JSON default vẫn flash). |

## 5 yêu cầu spec

| # | Kết quả | Bằng chứng |
|---|---|---|
| 1 choices từ JSON | ✅ | `--help` = `{agy,dsh,grok,codex,gemini,claude,opencode,goose,zeroclaw,jules,openrouter}` |
| 2 dsh ghim | ✅ | dump-config `resolved=deepseek-v4-pro` **EXIT 0**. Live `served_model=deepseek-v4-pro` **EXIT 0** |
| 3 auto ≠ flash (dsh) | ✅ | auto→pro. JSON `default_model` vẫn flash |
| 4 `--doctor` ≥3 | ✅ | dsh stdout 21138B **EXIT 0**. grok **EXIT 0**. goose: không verify **EXIT 1** |
| 5 traps → stderr | ✅ | `printf '' \| $PY bin/dispatch.py dsh --result-json 2>/dev/null` stdout JSON sạch. stderr 5 traps. **EXIT 1** (prompt rỗng) |

## Ác ý (mã thoát thật, không pipe)

| Ca | Exit | Output |
|---|---|---|
| vendor `khongco` | **2** | argparse `invalid choice` |
| model lạ dsh / agy | **2** | `not in vendor '…' valid models` |
| slug lạ claude (chưa biết list) | **0** | warning + dump JSON |
| JSON hỏng (bản sao) | exception | `JSONDecodeError` |
| thiếu `schema_version` | exception | `ValueError: schema_version != 3 (got None)` |
| thiếu key `vendors` | 0 (lib) | `vendor_names=[]` |
| `models` dict (bản sao) | exception | `ValueError: … sai dạng: dict` |
| `--cd /tmp/pk-qa-no-such-dir-xyz` grok | **1** | `status=error served_model=grok-4.6` (có `-m`) |
| `DEEPSEEK_API_KEY` cắt + `security` giả | **1** | `MISSING_CREDENTIAL` `served_model=deepseek-v4-pro` — không im |
| goose / jules (thiếu headless) | **1** | `missing_fields` `served_model=null` |

## Ràng buộc

| Check | Kết quả |
|---|---|
| JSON lược đồ ↔ reader | `schema_version=3`. `git diff --quiet config/vendors.json` → `0`. Vá này không đụng JSON. |
| dependency mới | Không. Chỉ stdlib. |
| test | **151 passed 0 failed** EXIT 0. Đi CLI thật (auto→default→run_vendor). Khoá từng lỗi. |

Không sửa code / không sửa `vendors.json`.
