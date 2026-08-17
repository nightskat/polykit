# DAP-DISPATCH-V2
HỎNG 4 CHỖ

PY = `~/.pyenv/versions/3.11.8/bin/python` (`python` trên máy = EXIT 127).

## Phát hiện (nặng → nhẹ)

| # | Mức | Lỗi | Lệnh + output thật + exit |
|---|---|---|---|
| 1 | 🔴 | `--doctor` nuốt lỗi zero-quota, luôn in OK + **EXIT 0**. Báo cáo **giấu** 2 dòng lỗi agy. | `$PY bin/dispatch.py agy --doctor` stderr: `/bin/sh: /model: No such file or directory` + `/usage` tương tự rồi `[polykit] doctor: agy OK` **EXIT 0**. `$PY bin/dispatch.py dsh --doctor` stderr: `error: --profile <name> is required` ×2 rồi `doctor: dsh OK` **EXIT 0**. Gốc: `zero_quota_cmds` `/model` bị `shell=True` chạy như path; `dsh --dump-config` thiếu `--profile`. |
| 2 | 🔴 | `openrouter` mất khỏi CLI (REGISTRY còn, JSON v2 không có). Lane cũ gãy. | `$PY bin/dispatch.py openrouter --dump-config` → `invalid choice: 'openrouter'` **EXIT 2** |
| 3 | 🔴 | Spec «thêm vendor = sửa JSON» **sai**. 4 tên vào choices rồi `unknown_vendor`. | `printf hi \| $PY bin/dispatch.py opencode --no-traps --result-json` → `status=blocked reason=unknown_vendor` **EXIT 1**. goose/jules giống. JSON-only `{opencode,goose,zeroclaw,jules}`; REGISTRY-only `{openrouter}`. |
| 4 | 🟠 | Model không có trong `models` vẫn nhận. | `$PY bin/dispatch.py dsh totally-fake-model --dump-config` → `resolved_model: totally-fake-model` **EXIT 0**. Mock `run_vendor(..., model="totally-fake-model")` → `status ok served totally-fake-model` (không reject). |

## 5 yêu cầu spec

| # | Kết quả | Bằng chứng |
|---|---|---|
| 1 choices từ JSON | ⚠️ nửa | Bản sao JSON + `fakeco` → `vendor_names` có `fakeco` (11 tên). CLI không trỏ được file khác. Dispatch vẫn if/elif cứng → #3. |
| 2 dsh ghim pro | ✅ | `$PY bin/dispatch.py dsh --dump-config` → `resolved_model: deepseek-v4-pro` **EXIT 0**. `echo test \| $PY bin/dispatch.py dsh --result-json` → `model/served_model=deepseek-v4-pro status=ok` **EXIT 0** |
| 3 auto → default, dsh ≠ flash | ✅ CLI | dsh auto → pro (không flash). agy auto → `gemini-3.7-flash-high`. Lib còn `AGY_DEFAULT_MODEL=gemini-3.6-flash-medium` ≠ JSON. |
| 4 `--doctor` | ❌ | 4 vendor chạy được (dsh/grok/gemini/claude) nhưng OK giả — xem #1. |
| 5 traps → stderr | ✅ | `printf '' \| $PY bin/dispatch.py dsh --result-json 2>/dev/null` stdout = JSON `blocked` sạch, không chữ trap. stderr (không nuốt) có 5 traps. `--no-traps` stderr rỗng. **EXIT 1** (prompt rỗng). |

## Đối chiếu «Lệnh đã chạy»

| # | Báo cáo | Kết quả |
|---|---|---|
| 1 pytest 114 trước | KHỚP số cũ | `$PY -m pytest tests/ --ignore=tests/test_dispatch_v2.py -q` → **114 passed** EXIT 0 |
| 2 pytest 137 sau | KHỚP | `$PY -m pytest tests/ -q` → **137 passed in 12.75s** EXIT 0 (23 test v2) |
| 3–6 `python bin/dispatch.py …` | KHÔNG CHẠY ĐƯỢC | `python …` → `pyenv: python: command not found` **EXIT 127** |
| 3 dump-config dsh (qua PY) | KHỚP | như spec #2 |
| 4 dispatch dsh thật (qua PY) | KHỚP status/model | EXIT 0, `served_model=deepseek-v4-pro` |
| 5 `--doctor dsh` | LỆCH | Báo cáo 180+ dòng, giấu `error: --profile`. Thực tế 333 dòng stdout + 2 lỗi + vẫn OK |
| 6 `--doctor agy` | LỆCH / giấu lỗi | Có `agy OK` nhưng **không** ghi `/bin/sh: /model` và `/usage` |

## Ác ý (mã thoát thật)

| Ca | Exit | Output |
|---|---|---|
| vendor `khongco` | **2** | argparse `invalid choice` — không im |
| model lạ dsh | **0** | dump-config nhận slug — xem #4 |
| JSON hỏng (lib, bản sao) | exception | `JSONDecodeError: Expecting property name…` (CLI không bắt) |
| thiếu `schema_version` | exception | `ValueError: schema_version != 2 (got None)` |
| thiếu key `vendors` | **0** | `vendor_names` = `[]` — không crash |
| `DEEPSEEK_API_KEY` cắt + `security` giả | **1** | `MISSING_CREDENTIAL` `status=error` — không im |
| `--cd /tmp/pk-qa-no-such-dir` grok | **1** | `Failed to set working directory… os error 2` |

## Ràng buộc

| Check | Kết quả |
|---|---|
| `git diff config/vendors.json` | **KHÔNG trống** (v1→v2, +181). mtime JSON 11:49 < `vendor_config.py` 11:55 → phiên dispatch **có lẽ không** sửa thêm. |
| dependency mới | Không. `requirements.txt` chỉ stdlib; import mới = `json/pathlib/functools/tempfile`. |
| test cũ | **114 passed** EXIT 0 |

Không sửa code / không sửa `vendors.json`.
