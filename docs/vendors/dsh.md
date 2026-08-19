# dsh (DeepSeek Harness) — lane thợ máy rẻ, SỬA ĐƯỢC FILE

> Số liệu LIVE: `/polykit:doctor`. Catalog: `curl -H "Authorization: Bearer $DEEPSEEK_API_KEY" https://api.deepseek.com/models`.
> Khảo sát gói: **`@deepseek-ai/dsh@0.1.0-rc.6`** (MIT, repo `deepseek-ai/deepseek-harness`), đọc thẳng ngày 2026-08-19.

`dsh` không phải CLI có vài cờ. Nó là **runtime plugin Cordis**: mọi tool, sandbox, adapter LLM
đều là một hàng cấu hình có `id` + `config`. Vì thế hầu hết knob **không có cờ dòng lệnh** —
chỉnh bằng patch YAML.

## Model
| Slug | Ghi chú |
|---|---|
| `deepseek-v4-pro` | **Dùng cái này cho việc thật.** PolyKit tự resolve `auto` → pro |
| `deepseek-v4-flash` | Mặc định của CLI. 🔴 **TRẢ VỀ RỖNG trên task nhiều bước** — tái hiện 2 lần (14/08, 16/08) |

Danh sách KHÔNG phải whitelist: id lạ vẫn đi thẳng lên wire. Ctx mặc định 1.000.000, output cap 256.000.

## Cài & auth
```
npm install -g @deepseek-ai/dsh
export DEEPSEEK_API_KEY=...        # BẮT BUỘC — dsh không đọc Keychain
```
Thiếu key → `MISSING_CREDENTIAL`. Đổi endpoint bằng `DEEPSEEK_BASE_URL`.

## Gọi qua PolyKit
```
/polykit:dispatch dsh -- <prompt>
```

## Gọi tay
```
dsh --profile headless "<task>"
dsh --profile headless --patch ./pro.yml "<task>"
```
⚠️ Cờ của launcher phải đứng **TRƯỚC** task — token đầu tiên nó không hiểu là bắt đầu arg của app.
Đặt `--patch` sau task thì nó bị nuốt thành văn bản.

## Chỉnh cấu hình = patch YAML
Target theo `id`, ghi đè `config`. `--patch` **lặp được**, chồng theo thứ tự.
```yaml
- id: agent-default-model
  config:
    provider: deepseek-official   # THIẾU dòng này -> gãy lúc boot: "$.provider missing required value"
    model: deepseek-v4-pro
- id: llm-deepseek
  config:
    reasoningEffort: max          # off | high | max — mặc định high
```
🔑 **`--dump-config` xác minh patch đã ăn mà KHÔNG tốn token** — in cây cấu hình rồi thoát.
Dùng nó trước mọi lần bắn việc thật.

### Bump effort trước khi bump model
`reasoningEffort` là `off | high | max`, mặc định `high`. Đây là nấc rẻ hơn việc đổi model.
Giá trị lạ → `UNSUPPORTED_REASONING_EFFORT`, chết **trước** khi gọi mạng (không mất tiền).
`off` serialize thành `thinking.type: disabled`.

### Knob khác hay dùng
| id | Knob |
|---|---|
| `llm-deepseek` | `apiKeyEnv` · `baseURL` · `thinking` · `maxTokens` (256000) · `streamIdleTimeoutMs` (300000) · `defaultContextWindow` (1000000) · `retryPolicy` |
| `tool-result-pruner` | `thresholdChars` 8192 / `headChars` 4096 / `tailChars` 1024 |
| `spill-policy` | `maxInlineBytes` 50000 |
| `tool-ralph` | `maxRounds` 64 — vòng lặp tự chạy dựng sẵn |
| `tool-subagent` | provider `spawn` (nền) / `fork` (một phát) |
| `persona` | đổi system prompt; `complete: true` = thay TOÀN BỘ |

## Quyền & sandbox — không có cờ, dùng biến môi trường
`DSH_PERMISSION_MODE`:

| Giá trị | sandbox | approval |
|---|---|---|
| `read-only` | read-only | ask |
| `workspace-write` | workspace-write | ask ← **mặc định** |
| `danger-full-access` | full | never |

`workspaceRoot` = thư mục gọi lệnh. Chạy headless thì không ai bấm "ask", nên việc ghi ra
ngoài workspace sẽ kẹt — đó là gốc của bẫy "nó ghi sang /tmp rồi báo lại".

## Năng lực có sẵn
bash + bash bền (PTY) · fs · fs-search · web + `web-search-deepseek` · skill (**đọc `SKILL.md`,
cùng định dạng Claude Code**) · todo · goal · jobs nền · plan mode · MCP client ·
subagent/fork/workflow · ralph loop · compaction + token-meter · phiên JSONL + SQLite.

Lớp LLM trung lập vendor (`dsh-llm` là adapter registry) — về nguyên tắc cắm được provider khác.

## Bẫy
- 🔴 `deepseek-v4-flash` trả rỗng trên task nhiều bước. PolyKit đã cứng hoá `auto` → `v4-pro`.
- Mất mạng giữa chừng → `TRANSPORT` error, **mất trắng cả lượt**. Luôn dặn agent **ghi file sớm**.
- Không đọc Keychain — key phải bơm qua biến môi trường.
- Patch thiếu `provider` → gãy **lúc boot**, không phải lúc chạy.
- `--resume` **KHÔNG có** ở profile `headless` (`--help` chỉ liệt kê `task` và `-h`). Nó là cờ của
  profile khác (`tui`/`web`). Bản ghi cũ "dsh --resume <session>" là sai, chép nhầm từ ví dụ README.

## Quota / giá
Trả theo lượt, không phải gói. Số dư: `curl -H "Authorization: Bearer $DEEPSEEK_API_KEY" https://api.deepseek.com/user/balance`.
Đo 17/08: **$0,39 cho 4 việc thật**. Giảm giá 16:30–00:30 UTC (23:30–07:30 giờ VN).

## PII
❌ **CẤM.** `dsh` gửi dữ liệu sang DeepSeek và sửa được file cục bộ — chỉ dùng cho code công khai.
Khử định danh trước hoặc chuyển về Claude host. Xem `../CHIA-VIEC.md` §PII.

## Live test qua PolyKit (2026-08-19)
Dispatch thật qua `bin/dispatch.py dsh --timeout 300 --result-json`, việc có đáp án kiểm được
(tổng số nguyên tố < 1000 = **76127**):

- `status: ok` · `served_model: deepseek-v4-pro` (resolve từ `auto`, KHÔNG rơi về flash) · `warnings: []`
- stdout đúng `76127`
- **Dấu vết phụ**: `solve.py` và `ketqua.txt` có thật trong thư mục gọi lệnh — chạy lại `solve.py`
  độc lập vẫn ra `76127`. Nghĩa là nó thật sự ghi file và chạy, không phải nhẩm ra con số.
- Số dư trước/sau đều `$11.14` → chi phí dưới ngưỡng hiển thị 2 chữ số thập phân (< $0,01).
