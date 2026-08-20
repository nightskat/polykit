# PolyKit — sổ bug

> **Luật**: agent nào dùng PolyKit mà thấy hành vi sai thì ghi vào đây NGAY, kèm lệnh nguyên văn
> và cái đã ĐO được. Sửa được trong phiên thì sửa luôn và ghi bằng chứng. File này **phải nằm
> trong git** — 18/08 nó từng nằm untracked một ngày, không ai thấy.
> Trạng thái: 🔴 MỞ · ✅ ĐÃ SỬA · ⚪️ ĐÓNG (không phải bug).

## Phiên 18/08/2026

> Dispatch thật: soát chéo 1 bộ hồ sơ tín dụng, prompt 37.073 byte (5 file Word đã thay PII).
> Lệnh: `cat full_prompt.txt | python3 bin/dispatch.py codex gpt-5.5 --timeout 580 --result-json`

## ✅ Chạy đúng — kết quả tốt
`status=ok`, `exit_code=0`, `vendor=codex`, `model=gpt-5.5`, `served_model=gpt-5.5`, `warnings=[]`.
Nội dung: **8 phát hiện, hội tụ 4/4 lỗi chính** mình đã tự bắt (số tiền 450 vs 300, lãi suất
9,9% vs 12%, mục đích copy nhầm hồ sơ, số HĐTC cụt) — **0 ảo giác**, đúng định dạng yêu cầu.
Chi phí ~1 lượt codex thay vì tự đọc lại 5 file bằng model chính. **Đây là ca dùng đúng của PolyKit.**

## ⚪️ BUG-1 — dòng `[polykit] served:` không in ra stderr → **KHÔNG phải bug** (đóng 19/08)

Memory `reference_polykit_silent_degrade` ghi *"dòng `[polykit] served: <model>` in ra **stderr**"*.
Đo lần này: `2> codex_stderr.txt` → **file 0 byte**. Dòng `served:` không xuất hiện ở đâu cả.

Không nguy hiểm (field `served_model` trong `--result-json` vẫn có và đúng), nhưng:
- ai chạy **không** kèm `--result-json` thì **mất hẳn** dấu vết model thật;
- memory hiện đang mô tả sai hành vi → cần sửa memory HOẶC trả lại dòng stderr.

**Kết luận 19/08** — đọc `bin/dispatch.py:196`: dòng đó chỉ in **khi `served_model != resolved_model`**.
Lượt 18/08 gọi `codex gpt-5.5` và được phục vụ đúng `gpt-5.5` → trùng nhau → im lặng **theo thiết kế**.
Tái lập 19/08 với `dsh` (`served=resolved=deepseek-v4-pro`): stderr cũng không có dòng `served:`. Nhất quán.
⇒ Không sửa code. Đã sửa **tài liệu**: `commands/dispatch.md` nói rõ dòng này chỉ xuất hiện khi model
thật KHÁC model yêu cầu, và `--result-json` mới là nguồn chính thức. Memory mô tả sai cần sửa theo.

## ✅ BUG-2 — prompt dài không có đường truyền file (đã sửa 19/08)

`dispatch.py` chỉ nhận prompt qua **stdin**. Với prompt 37 KB thì `echo "<prompt>" |` như
`commands/dispatch.md` hướng dẫn là **không dùng được** (quoting + xuống dòng + dấu tiếng Việt).
Phải tự viết `cat file | python3 …`.

**Đã sửa 19/08**: thêm `--prompt-file <path>` vào `bin/dispatch.py`. File không đọc được hoặc rỗng
→ exit 2, chặn **trước** khi gọi vendor. `commands/dispatch.md` viết lại: stdin cho prompt một dòng,
`--prompt-file` cho prompt dài/nhiều dòng/có dấu.
Bằng chứng: `tests/test_prompt_file.py` (3 test) + **live test thật** qua `dispatch.py dsh
--prompt-file` với prompt tiếng Việt nhiều dòng có dấu ngoặc kép → `status=ok`,
`served_model=deepseek-v4-pro`, stdout `3` (đúng: *"Đường vô xứ Nghệ quanh quanh"* có 3 chữ mang
dấu thanh — ờ, ứ, ệ), và file `dem.py` + `ketqua2.txt` có thật trong thư mục.

## 🔴 QUAN SÁT-3 — không có cổng chặn PII
`dispatch.py` gửi thẳng stdin ra vendor, **không kiểm tra gì**. Luật lane PGBank bắt phải qua
`pg-redact check` exit 0 trước khi gửi — nhưng chính `pg-redact` đang hỏng với văn xuôi
(xem `~/Claude/Build/tools/pg-redact/BUGS_2026-08-18.md`), nên luật đó **không thi hành được**
bằng máy, chỉ còn kỷ luật tay.
⇒ Nếu sau này vá pg-redact, đáng cân nhắc `dispatch --require-clean` gọi `pg-redact check`
làm cổng cứng. **Chưa làm bây giờ** — luật 3 lần đau, đây mới là lần 1.

## ⏱️ Số liệu
- Prompt 37 KB · timeout đặt 580s (trần cứng 600s vẫn đúng như memory ghi) · chạy trọn, không chạm trần.


## Phiên 19/08/2026

### ⚪️ Bản cài và repo đã tách nhau (đã hoà, không phải bug code)
`~/.claude/plugins/marketplaces/polykit` đứng ở `fa09257` trong khi repo đi thêm 15 commit —
bản cài kẹt ở kiến trúc trước `lib/vendor_config.py`, `vendors.json` còn schema v1, nên
**không có vendor `dsh`** dù registry repo đã có. Thêm nữa nó mang sửa đổi chưa commit của
phiên 18/08 (chính là file bug này).
Đã xử: đóng gói việc chưa commit thành nhánh `port/2026-08-18-docs`, merge về repo (`daf3faf`),
rồi đồng bộ một chiều repo → bản cài. 153 test xanh.
⇒ Bài học: **sửa trong bản cài là sửa vào chỗ sẽ bị ghi đè**. Sửa ở `~/Developer/polykit`, rồi đồng bộ.

### ✅ Adapter mỗi vendor trôi vì populate là HÀNH ĐỘNG, không phải TRẠNG THÁI (sửa 19/08)
Đo được: Claude ghim cache ở commit 03/08 · Codex ghim bản 14/07 (`0.2.1+codex.local`) ·
Gemini dùng extension `cross-cli-dispatch` v0.1.0 **ngày 05/05**, không gọi PolyKit dòng nào và
còn quảng cáo model đã chết (`o3`, `o4-mini`) · Grok chưa cài · agy chưa có.

Cái thiếu không phải "chạy populate lần nữa" mà là **một lệnh kiểm tra được**.
⇒ `bin/populate.py`: `--check` in bảng 5 vendor + cờ lệch, `--apply` sinh adapter và gọi lệnh
update của từng CLI. Adapter được SINH từ `commands/*.md`, không sửa tay.

Điểm mấu chốt phát hiện được lúc làm: **Claude Code không chạy thư mục marketplace** mà chạy
bản chép ở `cache/polykit/polykit/<ver>/` ghim theo `gitCommitSha`. Test vào `marketplaces/…`
là test nhầm thứ hai — đã dính đúng lỗi này một lần trong phiên.
Codex/Gemini không có vấn đề đó: adapter chỉ là CHỮ, engine gọi thẳng `bin/dispatch.py` của repo.

### 🔴 BUG-4 — `doctor` báo `ready` cho vendor ĐANG BỊ CAP (19/08, bằng chứng sống)
19/08 lúc 13:5x, đo trực tiếp trong cùng một phiên:
- `codex exec …` → `ERROR: You've hit your usage limit … try again at Aug 20th 10:58 AM`
- `gemini -p …` → `429 TerminalQuotaError: You have exhausted your daily quota`

Ngay sau đó `python3 bin/doctor.py` in **7/7 `ready`**, gồm cả `codex` và `gemini`.

⇒ `doctor` đang đo **"binary có tồn tại và chạy được `--version` không"**, chứ không đo
**"gọi được không"**. Với người dùng thì hai thứ đó khác hẳn: bảng xanh mà dispatch chết ngay.
Đây chính là điểm yếu M3 mà BACKLOG đã ghi (cap-detect dựa vào parse stderr) — nay có bằng chứng
sống thay vì suy đoán.
**Việc cần làm**: `quota_capped` phải suy ra từ lần dispatch thất bại gần nhất (đã có
`state_store`), hoặc đọc quota từ local credentials/logs như OpenUsage/CAUT (BACKLOG đã khảo sát).
Trước mắt: **đừng tin cột `ready` như bằng chứng gọi được.**

---

## Phiên 19/08/2026 — dispatch review script `pg-timkho`

> Bối cảnh: nhờ vendor review một bản vá Python ~11KB. Cả 2 vendor đều KHÔNG trả được kết quả,
> nhưng cách hỏng khác nhau và cả hai đều làm mất dấu vết nguyên nhân.

### ✅ BUG-5 — `--result-json` nuốt mất DÒNG LỖI THẬT của vendor (đã sửa 20/08)

**Lệnh nguyên văn**
```
python3 bin/dispatch.py codex --cd <repo> --prompt-file <file> --timeout 540 --result-json
```
**Đo được**: `status=error`, `exit_code=1`, `reason=vendor_exit_nonzero`, `stdout=""`.
Mảng `warnings` chỉ chứa **banner khởi động + phần echo lại prompt** (workdir, model, provider,
approval, sandbox, session id, rồi tới nội dung prompt) — **cắt đúng trước dòng lỗi**.

Nguyên nhân thật chỉ lộ ra khi chạy TAY:
```
codex exec --skip-git-repo-check "Nói đúng một chữ: OK" < /dev/null
→ ERROR: You've hit your usage limit. ... try again at Aug 20th, 2026 10:58 AM.
```
**Tác hại**: `vendor_exit_nonzero` không phân biệt được *hết quota* (chờ tới mai) với *lỗi cờ*
(sửa lệnh là chạy) hay *lỗi mã nguồn*. Agent đọc `--result-json` sẽ đoán mò, hoặc tệ hơn là
thử lại vô ích cho tới khi hết luôn vendor dự phòng.
**Việc cần làm**: `warnings` phải giữ **N dòng CUỐI** của stderr (nơi lỗi nằm), không phải N dòng
đầu; và bắt riêng mẫu `hit your usage limit` → `reason=quota_capped` để failover đi đúng nhánh.
**Đã sửa 20/08** — hoá ra là **ba** khuyết tật chồng nhau, không phải một:
1. `warnings = stderr.splitlines()[:20]` lấy dòng ĐẦU → đổi sang giữ 3 dòng đầu (banner
   version/model, cần để tái lập ca) + 20 dòng CUỐI, có dòng ghi rõ đã bỏ bao nhiêu ở giữa.
2. Mẫu quota không khớp nguyên văn: codex in `You've hit your usage limit`, gemini in
   `exhausted your daily quota` — cả hai đều trượt `usage limit reached`. Đã thêm mẫu.
3. 🔴 **Mới lộ ra khi vá (2) — PolyKit đọc chính chữ của mình.** `codex exec` **echo prompt ra
   stderr** (đo được: dòng 13-14). `is_quota_error` quét toàn bộ stderr, nên một prompt chứa
   cụm "hit your usage limit" — ví dụ đang nhờ review chính `docs/BUGS.md`, file này có cụm đó
   4 lần — bị xếp nhầm `quota_capped`. Tức bản vá (2) tự đẻ ra lỗi ngược chiều với mục tiêu.
   ⇒ `strip_echoed_prompt()` bỏ khối echo trước khi dò. Chỉ bỏ khi khớp LIỀN KHỐI, thà giữ
   thừa còn hơn xoá nhầm dòng lỗi thật.

⚠️ **Bài học quy trình**: lỗi (3) do **review khác họ** (dsh/DeepSeek) chỉ ra, sau khi codex
(OpenAI) đã review bản vá trước và không thấy. Và bản vá cho (3) **unit test xanh nhưng LIVE
TEST đỏ**: so khớp liền-khối nguyên văn trượt vì codex giữ lại dòng trống của prompt. Chỉ khi
dispatch thật với prompt dài mới lộ. Test xanh vẫn không thay được live test.
**Trạng thái**: ✅ ĐÃ SỬA — 170 test xanh + live test (`status=error`, `reason=vendor_exit_nonzero`,
lỗi 400 thật hiện trong `warnings`, echo prompt đã sạch).

### 🟡 BUG-9 — 4 đường nuốt lỗi thật (nhánh TIMEOUT đã sửa 20/08, còn 3)
Bản vá BUG-5 chỉ chạm nhánh `returncode != 0` của `_classify_completed`. Còn:
1. ✅ **Timeout — ĐÃ SỬA 20/08.** `TimeoutExpired` mang theo `e.stdout`/`e.stderr` (phần vendor
   kịp in trước khi bị giết); trước đây vứt sạch. Nay giữ lại, bỏ echo prompt, cắt bằng
   `tail_lines`, gắn nhãn `[vendor:stdout|stderr]` vs `[polykit]`.
   `stdout` khi timeout để **RỖNG có chủ ý** — trường đó là "kết quả vendor", nhét nửa vời vào
   thì caller chỉ kiểm `stdout != ""` sẽ đọc dở dang thành kết quả thật, và JSON phình không
   giới hạn (Codex review). Phân biệt thêm 3 ca: im lặng thật · chỉ có echo prompt · có manh mối.
2. **`returncode == 0`**: trả `ok` ngay, stderr bị vứt hoàn toàn — mất cảnh báo degraded/quota.
3. **`_dispatch_gemini`**: không đi qua `_classify_completed`, lane fail chỉ ghi
   `"lane N failed (...)"`, stderr thật không bao giờ lộ.
4. **Vendor ghi lỗi ra stdout** (nhất là `--json`): bản vá chỉ nhìn `stderr`.

### 🔴 BUG-6 — task ĐỌC FILE làm vendor timeout, `stdout` rỗng (đo trên CẢ `grok` LẪN `dsh`)

**Lệnh nguyên văn**
```
python3 bin/dispatch.py grok --cd <repo> --prompt-file <file> --timeout 540 --result-json
```
**Đo được**: `status=timeout`, `exit_code=124`, `model=None`, `stdout=""` sau đủ 540s.

Đã loại trừ "grok chết": cùng cấu hình, prompt 1 dòng (`Nói đúng một chữ: OK`) trả về
`status=ok`, `exit_code=0`, `stdout="OK\n"`, `served_model=grok-4.6` trong <120s.
Khác biệt duy nhất: prompt dài yêu cầu grok **tự đi mở file** (`./pg-timkho.py`, `./patch.diff`).
Nghi vấn (CHƯA chắc): pha agentic đọc file bị treo hoặc chạy rất chậm dưới sandbox read-only.

**Tác hại**: đốt trọn 540s mà không có gì để nghiệm thu, và `stdout` rỗng nên không biết nó
đã làm được tới đâu — không phân biệt được "treo ngay từ đầu" với "gần xong thì hết giờ".
**Cách đi vòng đã dùng, có hiệu lực**: nhúng thẳng nội dung file vào prompt thay vì bắt vendor
tự mở (prompt 20.7KB). Nên viết thành khuyến nghị trong sổ trap của grok:
*"đừng giao task đọc file cho grok — đưa nội dung vào prompt"*.
**Cập nhật cùng phiên — KHÔNG phải lỗi riêng của grok**: `dsh` (deepseek-v4-pro) chạy CÙNG prompt
đó cũng `status=timeout`, `exit_code=124`, `stdout=""` sau 540s.

**🔴 ĐÍNH CHÍNH (cùng phiên) — giả thuyết "tại task đọc file" là SAI.**
Đã chạy lại cả hai vendor với prompt **nhúng sẵn toàn bộ mã nguồn** (không phải mở file):
`grok` 20.7KB → timeout 420s, `stdout=""`. `dsh` 20.7KB → timeout 420s, `stdout=""`.
Bỏ đường dẫn đi mà vẫn hỏng y hệt → **đọc file không phải biến số**.

Tách biến bằng thí nghiệm đối chứng (cùng vendor, cùng cấu hình, chỉ đổi ĐỘ DÀI ĐẦU RA):

| Prompt | Vào | Ra yêu cầu | Kết quả |
|---|---|---|---|
| 1 dòng | 22 byte | 1 chữ | ✅ ok, <120s |
| **toàn bộ script + "trả lời đúng một chữ OK"** | **15.186 byte** | **1 chữ** | **✅ ok, 9,5s** |
| script + yêu cầu review đầy đủ | 20.717 byte | dài | ❌ timeout 420s, rỗng |
| yêu cầu review, tự mở file | ~3KB | dài | ❌ timeout 540s, rỗng |

**🔴 ĐÍNH CHÍNH LẦN 2 — "tại đầu ra dài" cũng SAI.** Chạy tiếp 2 phép đo nữa, bảng đầy đủ:

| Prompt | Vào | Việc phải làm | Ra | Kết quả |
|---|---|---|---|---|
| 1 dòng | 22 B | không | 1 chữ | ✅ <120s |
| script + "trả lời OK" | 15.186 B | không | 1 chữ | ✅ 9,5s |
| **script + "liệt kê tên 3 hàm def"** | **15.186 B** | **đọc + trích** | **3 dòng** | **✅ ok** |
| script + review, **chặn 6 phát hiện × 3 dòng** | ~16 KB | phân tích | ngắn | ❌ timeout 420s, rỗng |
| script + review đầy đủ | 20.717 B | phân tích | dài | ❌ timeout 420s, rỗng |

Đọc 15KB: được. Trích xuất từ 15KB: được. Đầu ra 3 dòng: được. **Chặn đầu ra vẫn timeout.**
→ Biến số KHÔNG phải kích thước đầu vào, KHÔNG phải đọc file, KHÔNG phải độ dài đầu ra.
Thứ còn lại phân biệt được 2 nhóm là **độ sâu suy luận** của task (trích xuất vs phân tích).
Chưa biết vì sao — **ghi là CHƯA BIẾT**, không đoán tiếp.

Ba lần mình đưa nguyên nhân, hai lần sai, mỗi lần đều "nghe rất hợp lý" và đều dựa trên 2 mẫu
cùng chiều. Bài học ghi kèm: có 2 mẫu cùng chiều thì đó là **giả thuyết**, muốn thành nguyên nhân
phải có mẫu ĐỐI CHỨNG bác được nó — ở đây chính là dòng "liệt kê tên 3 hàm".

**Việc cần làm**: (a) stream/giữ output từng phần khi timeout thay vì trả rỗng — hiện 540s đổi
lấy 0 byte, không nghiệm thu được gì; (b) trap chung: task phân tích phải kèm hạn mức đầu ra
(số phát hiện tối đa, số dòng mỗi phát hiện).
**Trạng thái**: 🔴 MỞ.

---

## Phiên 20/08/2026 — dispatch sửa `scan-job.sh` (scanbox)

### 🟢 BUG-7 — `--cd` trỏ vào thư mục KHÔNG-git → codex luôn exit 1 (ĐÃ SỬA)

**Lệnh nguyên văn**
```
python3 bin/dispatch.py codex --prompt-file <file> --sandbox workspace-write \
  --cd /Users/nightskat/Claude/Build/infra/server-pii-cuc-bo --result-json --timeout 480
```
**Đo được**: `status=error`, `exit_code=1`, `warnings=["Reading prompt from stdin...",
"Not inside a trusted directory and --skip-git-repo-check was not specified."]`.

**Nguyên nhân** (`bin/lib/dispatch_core.py:63-67`, `build_codex_cmd`): cờ
`--skip-git-repo-check` nằm trong **nhánh `else` của `if workdir`**. Tức là chỉ thêm khi
KHÔNG có `--cd`. Nhưng hai điều kiện đó độc lập nhau: `-C` chọn thư mục làm việc, còn
`--skip-git-repo-check` trả lời câu "thư mục đó có phải git repo không". Thư mục hạ tầng
(`server-pii-cuc-bo`) không phải git repo → mọi lượt dispatch có `--cd` đều chết.

**Nghịch lý cần nhớ**: bỏ `--cd` đi thì lại CHẠY ĐƯỢC (rơi vào nhánh `else`) — nên triệu chứng
đọc như "cờ `--cd` hỏng", trong khi thật ra là cờ khác bị treo nhầm chỗ.

**Đã sửa**: `cmd.append("--skip-git-repo-check")` ra ngoài, chạy vô điều kiện.
Test `tests/test_dispatch_builders.py` cập nhật theo — `156 passed`.
**Live test 20/08 10:31** — chạy lại đúng lệnh trên với bản đã sửa: dòng "Not inside a trusted
directory" BIẾN MẤT, codex đi hết đường tới API và chỉ còn chết vì hạn mức
(`You've hit your usage limit ... 10:58 AM`). Tức cờ đã ăn — lỗi còn lại là BUG-5, khác lớp.
**Trạng thái**: 🟢 ĐÃ SỬA (unit test 156 passed + live test).
⚠️ Bản CÀI ở `~/.claude/plugins/cache/.../polykit/0.5.0/` VẪN CÒN LỖI cho tới lần cập nhật
plugin kế tiếp — sửa ở repo theo đúng luật, đừng vá vào bản cài.

---

## Phiên 20/08/2026 — bench OCR, dispatch maker/tester

### 🟡 BUG-8 — `--result-json` KHÔNG in JSON khi lỗi sớm → caller nhận file 0 byte

> Đánh số lại từ BUG-7 → BUG-8 lúc 10:33 20/08: hai phiên Claude chạy song song trên cùng repo
> cùng đặt tên "BUG-7" cách nhau vài phút. Mục này commit sau (`5996a13`) nên nhường số.

**Đo được** (3 ca, đều `exit=2`, đều `stdout = 0 byte`):
```
dispatch.py agy gemini-3.1-pro --prompt x --result-json   # model không hợp lệ
dispatch.py agy --model x --prompt x --result-json        # cờ không tồn tại
```
Thông báo lỗi có đầy đủ và rất tốt — nhưng nằm ở **stderr**, còn **stdout rỗng**.

**Vì sao vẫn là bug**: cờ `--result-json` hứa "stdout là JSON". Người gọi vì thế viết
`dispatch.py ... --result-json > out.json` rồi `json.load(out.json)`. Khi lỗi sớm, out.json
**0 byte** → `JSONDecodeError`, và triệu chứng **trông y hệt** vendor chết/timeout.
Mình đã tự dẫm đúng bẫy này 3 lần trong 1 phiên và suýt kết luận "agy hỏng" trong khi lỗi là
tên model mình gõ sai.

**Không phải lỗi che giấu thông tin** — PolyKit báo đúng, `exit=2` đúng. Lỗi ở chỗ **hợp đồng
đầu ra không đồng nhất**: lúc thì JSON, lúc thì rỗng.
**Việc cần làm**: khi có `--result-json`, mọi đường thoát đều in JSON, ví dụ
`{"status":"error","reason":"invalid_model","stderr":"...","exit_code":2}`.
**Trạng thái**: 🟡 MỞ (nhẹ — có đường vòng: bỏ `--result-json` là thấy lỗi ngay).

### 🔴 BUG-6 — thêm bằng chứng: `grok` hỏng ở việc SINH CODE, `dsh` thì không

Phiên 20/08, cùng khung dispatch, 3 việc thật:

| Việc | Vendor | Kết quả |
|---|---|---|
| Nghiên cứu 6 model OCR, đầu ra có khuôn cứng | `dsh` | ✅ ok, 1.730 byte |
| Viết `cham.py` (~1,6 KB code) | `dsh` | ✅ ok |
| Viết bộ test đập `cham.py` | `grok` | ❌ timeout, `stdout` rỗng |

→ Cộng với 3 lần hôm 19/08, `grok` đã **4/4 lần timeout rỗng** trên việc sinh/phân tích code,
trong khi `dsh` cùng khung, cùng cỡ prompt thì chạy tốt. Giả thuyết "tại prompt dài / tại đọc
file / tại đầu ra dài" đều đã bị bác ở mục trên.
**Khuyến nghị dùng ngay**: đừng giao việc sinh code cho `grok`; dùng `dsh`, để `grok` cho việc
ngắn có khuôn.
**Trạng thái**: 🔴 MỞ, nguyên nhân CHƯA BIẾT.

### ✅ BUG-10 — chính `populate.py` báo cáo sai 2 vendor (sửa 20/08, ngay trong lượt đầu dùng thật)
- **grok**: hàm cũ chỉ hỏi "có cài chưa", cài rồi thì `--apply` **bỏ qua**. Nhưng grok **chép code
  về**, không trỏ vào repo → nó trôi. Đo được: bản grok đứng ở `b655c67`, thiếu bản vá BUG-7.
  ⇒ so nội dung `dispatch_core.py` với repo, và gọi `grok plugin update`.
  ⚠️ `grok plugin update` kéo từ GitHub nên **chỉ thấy commit đã PUSH**.
- **agy**: dòng "kế thừa qua import từ gemini-cli" là **giả định chưa kiểm**, viết ra rồi tin luôn.
  Thực tế `agy plugin list` chỉ có `superpowers` — polykit chưa từng có mặt.
  ⇒ gọi `agy plugin import gemini` sau khi ghi xong thư mục gemini.

Dọn kèm: `agy plugin import gemini` kéo về cả `cross-cli-dispatch` cũ (quảng cáo `o3`/`o4-mini`
đã chết) — đã gỡ khỏi agy; bản gemini đã tắt từ 19/08.

**Bài học**: bảng trạng thái tự viết mà chưa đo thì cũng là một dạng "thành công giả" — nó cho
cảm giác đã kiểm soát trong khi 2/5 ô là chữ tự bịa.


### 🟡 BUG-6 — bớt bí: `dsh` KHÔNG stream, nên timeout không thể có output dở
Live test 20/08 sau khi vá BUG-9: ép `dispatch dsh --timeout 25` trên việc dài.
```
status=timeout · exit_code=124
warnings: [polykit] vendor KHÔNG kịp in gì ra stdout trước khi bị giết.
          [polykit] vendor KHÔNG kịp in gì ra stderr trước khi bị giết.
```
Tức **không phải PolyKit vứt mất** — vendor thật sự chưa ghi một byte nào vào pipe.
Khớp đúng README của dsh: `--profile headless` = *"answer one task, **print the final** assistant
message, and exit"*. In một lần ở cuối ⇒ bị giết giữa chừng thì vĩnh viễn rỗng, **theo thiết kế**.

⇒ Sửa lại cách hiểu BUG-6: "stdout rỗng khi timeout" **không phải triệu chứng của lỗi**, nó là
hành vi bình thường của vendor không stream. Câu hỏi thật còn lại là **vì sao task đó timeout**,
chứ không phải vì sao rỗng. Vá BUG-9 không gỡ được BUG-6 — nhưng nó **loại được một giả thuyết**
và làm ca im lặng nói ra thành lời thay vì `warnings=[]`.
**Chưa đo**: grok có stream không (nếu có thì cùng lệnh sẽ ra manh mối, và đó là hướng đào tiếp).
