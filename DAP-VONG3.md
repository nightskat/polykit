HỎNG 2 CHỖ
PY=`~/.pyenv/versions/3.11.8/bin/python` · `python` trần EXIT 127 · `pytest tests/ -q` → `142 passed in 1.00s` **EXIT 0**.

## Phát hiện mới — do bản vá đẻ (nặng → nhẹ)

| # | Mức | Lỗi | Lệnh + output thật + exit |
|---|---|---|---|
| 1 | 🔴 | Đổi `models` → `list\|null` rồi **chặn mọi slug khi `None`**. Spec: "chưa biết thì nói rõ **không chặn được**". Code `exit 2`. `claude`/`opencode`/`goose`/`jules`/`zeroclaw` **thiếu field** (`.get`=None, giống `gemini: null`). `auto` không dump/dispatch được. `openrouter` không có trong JSON → **không ghim được model nào**. | `$PY bin/dispatch.py claude --dump-config` → `cannot validate 'claude-opus-5'` **EXIT 2**. `claude claude-opus-5 --dump-config` **EXIT 2**. `opencode --dump-config` **EXIT 2**. `gemini gemini-2.5-pro --dump-config` **EXIT 2**. `openrouter some-or-model --dump-config` **EXIT 2**. `claude --allow-unknown-model --dump-config` mới ra `resolved=claude-opus-5` **EXIT 0**. |
| 2 | 🟡 | Nhánh đọc sót: chỉ `None` và `list` được xử lý. `dict`/`str` (lược đồ cũ) **lọt im**. Loader chỉ check `schema_version==3`, không enforce `_luat`. | `$PY -c` cùng `if/elif` với `valid_models={"ho":["slug"]}` → `BRANCH: SILENT ACCEPT type=dict` **EXIT 0**. JSON thật: agy/dsh/grok/codex=list, gemini=null, 5 vendor kia **không có key**. |

## 3 lỗi vòng 2 — đã hết (cùng lệnh v2)

| Lỗi cũ | Lệnh | Nay |
|---|---|---|
| doctor dsh luôn EXIT 1 | `$PY bin/dispatch.py dsh --doctor` | `doctor: dsh OK` **EXIT 0** (chạy thêm `dump-default-config`, stdout 21138B) |
| codex doctor ~304KB | `$PY bin/dispatch.py codex --doctor` | stdout **10319B** + `codex OK` **EXIT 0** (không còn `debug models`) |
| agy in trùng `/model` | `$PY bin/dispatch.py agy --doctor` | verify `/model` rồi zq `/usage` (khác lệnh) `agy OK` **EXIT 0** |
| mất binary bịa served | `env PATH=/usr/bin:/bin $PY bin/dispatch.py opencode --result-json --allow-unknown-model` | `status=skipped reason=not_installed served_model=null` **EXIT 1** |
| lệnh v2 không `--allow` | `printf hi \| $PY bin/dispatch.py opencode --no-traps --result-json` | **EXIT 2** (dính #1 — không còn đi tới served) |
| model bịa khi models≠dict | `$PY bin/dispatch.py claude totally-fake-model --dump-config` | **EXIT 2** `cannot validate` |

## Lệnh trong BAO-CAO-VONG3.md

| Lệnh | Đối chiếu |
|---|---|
| `dsh --doctor` EXIT 0 | KHỚP |
| `codex --doctor` 10211B EXIT 0 | LỆCH (thực 10319B, vẫn EXIT 0, không 300KB) |
| `agy --doctor` EXIT 0 | KHỚP |
| `claude totally-fake-model --dump-config` EXIT 2 | KHỚP |
| `PATH=… opencode --result-json --allow-unknown-model` served=null EXIT 1 | KHỚP |
| `pytest tests/ -q` 142 / 8.02s | LỆCH thời gian (`142 passed in 1.00s` EXIT 0) |
| `json.load(vendors.json)` EXIT 0 | KHỚP |

## 5 yêu cầu spec

| # | Kết quả | Bằng chứng |
|---|---|---|
| 1 choices từ JSON | ✅ | bản sao + `fakeco` → 11 tên. `--help` = 10 JSON + `openrouter` |
| 2 dsh ghim pro | ✅ | `dsh --dump-config` → `resolved_model=deepseek-v4-pro` **EXIT 0** |
| 3 auto ≠ flash (dsh) | ⚠️ | dsh auto→pro. **claude/opencode auto EXIT 2** (#1) |
| 4 `--doctor` ≥3 | ✅ | dsh/codex/agy/grok/gemini/claude **EXIT 0**. goose/OR: không verify **EXIT 1** |
| 5 traps → stderr | ✅ | `printf '' \| $PY bin/dispatch.py dsh --result-json 2>/dev/null` stdout JSON sạch. stderr 5 traps. `--no-traps` stderr rỗng. **EXIT 1** (prompt rỗng) |

## Ác ý (mã thoát thật)

| Ca | Exit | Output |
|---|---|---|
| vendor `khongco` | **2** | argparse `invalid choice` |
| model lạ dsh | **2** | `not in vendor 'dsh' valid models` |
| JSON hỏng (lib, bản sao) | exception | `JSONDecodeError: Expecting property name…` |
| thiếu `schema_version` | exception | `ValueError: schema_version != 3 (got None)` |
| thiếu key `vendors` | 0 (lib) | `vendor_names=[]` — không crash |
| `--cd /tmp/pk-qa-no-such-dir-xyz` grok | **1** | `os error 2` `status=error` |
| `DEEPSEEK_API_KEY` cắt + `security` giả | **0** | dsh vẫn `status=ok` (credential local) — **không im**: có stdout thật |

Không ca nào chết im `exit 0` trừ dsh còn key local.

## Ràng buộc

| Check | Kết quả |
|---|---|
| JSON được phép sửa (v3) | `schema_version=3`. `git diff --quiet config/vendors.json; echo $?` → **0** (đã commit). CODE đọc `!= 3`. `_luat` bắt list\|null — **5 vendor không điền** + reader chặn `None` = #1 |
| dependency mới | Không. `requirements.txt` chỉ stdlib; vá dùng `shlex` (stdlib) |
| test cũ | subset tos/degraded/guards/state/doctor **18 passed**. Cả bộ **142 passed 0 failed** EXIT 0 |

Không sửa code / không sửa `vendors.json`.
