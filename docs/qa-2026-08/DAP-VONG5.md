HỎNG 2 CHỖ
PY=`~/.pyenv/versions/3.11.8/bin/python` · `pytest tests/ -q` → `147 passed in 12.98s` **EXIT 0** · 11/11 `--dump-config` **EXIT 0** · revert `models is None`→`sys.exit(2)` → `2 failed, 145 passed in 12.01s` rồi hoàn nguyên `5 passed in 1.33s`.

## Phát hiện mới — do bản vá đẻ (nặng → nhẹ)

| # | Mức | Lỗi | Lệnh + output thật + exit |
|---|---|---|---|
| 1 | 🟠 | Vá `served_model=null` **chỉ khi `status==ok`**. CLI resolve auto→default rồi mới `run_vendor(slug)`. Fail/402 → `_classify_completed` bịa slug, không có warning «không nhận cờ model». Test mới gọi `model="auto"` nên không khoá đường CLI. | Fake `/tmp/pk-fakebin/opencode` + `export FAKE_OC_FAIL=1` · `printf hi \| $PY bin/dispatch.py opencode --no-traps --result-json --timeout 5` → `status=error served_model=qwen/qwen3.7-flash warnings=["boom: fake fail"]` **EXIT 1**. `FAKE_OC_QUOTA=1` → `status=skipped reason=quota_capped served_model=qwen/qwen3.7-flash exit_code=146` **EXIT 1**. Nhánh ok: `served_model=null` + warning trong JSON **EXIT 0**. `PATH=/usr/bin:/bin` → `not_installed served_model=null` **EXIT 1**. |
| 2 | 🟡 | Spec: warning «không nhận cờ model» phải **stderr VÀ `warnings[]`**. Vá chỉ nhét JSON. Text mode mất sạch. | Live `printf hi \| $PY bin/dispatch.py opencode --no-traps --result-json --timeout 20` stderr **chỉ** `[polykit] warning: model list for vendor 'opencode' is unknown, cannot validate 'qwen/qwen3.7-flash'`. `grep 'không nhận cờ model'` trên stderr **trống**. Text mode stdout=`Hi! How can I help you today?` stderr=cùng 1 dòng cannot-validate **EXIT 0**. |

## 2 lỗi vòng 4 — đã hết (nhánh được vá)

| Lỗi cũ | Lệnh | Nay |
|---|---|---|
| served_model bịa khi không ghim | `printf hi \| $PY bin/dispatch.py opencode --no-traps --result-json --timeout 20` | `served_model: null` + warning trong JSON **EXIT 0**. dsh mock có `--patch`; live `dsh deepseek-v4-flash` → `served_model=deepseek-v4-flash` **EXIT 0**. |
| 0 test khoá | tạm thêm `sys.exit(2)` sau warning `None`, `pytest tests/test_vong5.py -q` | `F...F` `2 failed, 3 passed in 0.92s` **EXIT 1** · `Expected 0 for claude, got 2`. Hoàn nguyên: `5 passed in 1.33s` **EXIT 0**. |

## Lệnh trong BAO-CAO-VONG5.md

| Lệnh | Đối chiếu |
|---|---|
| opencode `served_model: null` | **KHỚP** JSON + warning unknown-list **EXIT 0**. Họ không ghi việc warning «không nhận cờ» vắng stderr. |
| dsh flash `served_model` | **KHỚP** `served_model=deepseek-v4-flash` **EXIT 0**. **LỆCH stdout** (họ: «Chào bạn!…workspace `polykit`»; thật: «Hi Tuan!…PolyKit repo») — LLM khác lời, có chạy. |
| pytest `147 passed in 11.99s` | **KHỚP 147**. **LỆCH thời gian** (thật `12.98s`). Không kiểu gõ byte/giây từ nhớ như vòng 4. |
| revert `F...F` + assert claude got 2 | **KHỚP** failure #1. Họ cắt failure #2 (`test_ca_11_ten` / `claude-opus-5`). Restore `5 passed` **KHỚP**, thời gian `0.58s` vs `1.33s`. |

## 5 yêu cầu spec

| # | Kết quả | Bằng chứng |
|---|---|---|
| 1 choices từ JSON | ✅ | bản sao + `fakeco` → 11 tên. `--help` = 10 JSON + `openrouter` |
| 2 dsh ghim | ✅ | `dsh --dump-config` → `resolved_model=deepseek-v4-pro` **EXIT 0**. Live flash `served_model=deepseek-v4-flash` **EXIT 0** |
| 3 auto ≠ flash (dsh) | ✅ | dsh auto→pro. JSON `default_model` vẫn flash. |
| 4 `--doctor` ≥3 | ✅ | dsh stdout 21138B **EXIT 0**. agy `/model` rồi `/usage` **EXIT 0**. grok **EXIT 0**. goose: không verify **EXIT 1** |
| 5 traps → stderr | ✅ | `printf '' \| $PY bin/dispatch.py dsh --result-json 2>/dev/null` stdout JSON sạch. stderr 5 traps. `--no-traps` stderr rỗng. **EXIT 1** (prompt rỗng). |

## Ác ý (mã thoát thật)

| Ca | Exit | Output |
|---|---|---|
| vendor `khongco` | **2** | argparse `invalid choice` |
| model lạ dsh / agy | **2** | `not in vendor '…' valid models` |
| slug lạ claude (chưa biết list) | **0** | warning + dump JSON |
| JSON hỏng (bản sao) | exception | `JSONDecodeError` |
| thiếu `schema_version` | exception | `ValueError: schema_version != 3 (got None)` |
| thiếu key `vendors` | 0 (lib) | `vendor_names=[]` |
| `models` dict/str/int (bản sao) | exception | `ValueError: … sai dạng: dict/str/int` |
| `--cd /tmp/pk-qa-no-such-dir-xyz` grok | **1** | `os error 2` `status=error` |
| `DEEPSEEK_API_KEY` cắt + `security` giả | **1** | `MISSING_CREDENTIAL` `status=error` — không im |

## Ràng buộc

| Check | Kết quả |
|---|---|
| JSON lược đồ ↔ reader | `schema_version=3`. Loader chặn non-list. Thiếu `models` = unknown (warn). `jules.default_model` vẫn chuỗi mô tả `Google Jules Agent`. goose/jules/zeroclaw không `headless` → `blocked missing_fields` **EXIT 1** (cũ, không do vá này). |
| dependency mới | Không. `requirements.txt` chỉ stdlib. |
| test | **147 passed 0 failed** EXIT 0. Test mới khoá revert + nhánh ok; **không** khoá fail/402. |

Không sửa code / không sửa `vendors.json`.
