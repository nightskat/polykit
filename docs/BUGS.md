# PolyKit — sổ bug

> **Luật**: agent nào dùng PolyKit mà thấy hành vi sai thì ghi vào đây NGAY, kèm lệnh nguyên văn
> và cái đã ĐO được. Sửa được trong phiên thì sửa luôn và ghi bằng chứng. File này **phải nằm
> trong git** — 18/08 nó từng nằm untracked một ngày, không ai thấy.
> Trạng thái: 🔴 MỞ · ✅ ĐÃ SỬA · ⚪️ ĐÓNG (không phải bug).

## Mục lục

| Bug | Trạng thái | Mô tả |
|---|---|---|
| QUAN SÁT-3 | 🔴 MỞ | `dispatch.py` chưa có cổng chặn PII (`pg-redact check`) trước khi gửi stdin ra vendor |
| BUG-12 | ✅ ĐÃ SỬA | `--prompt "chữ"` bị argparse rút gọn thành `--prompt-file` → coi câu chữ là đường dẫn |
| BUG-13 | ✅ ĐÃ SỬA | probe auth hỏng vì lý do không-phải-auth vẫn dán nhãn `auth_unverified` và VỨT stderr |
| BUG-6 | 🔴 MỞ | **Chỉ còn `grok`** timeout rỗng khi sinh code (4/4). `dsh` đã gỡ oan 20/08: nó LÀM XONG, chỉ lâu hơn trần 600s |
| BUG-2 | ✅ ĐÃ SỬA | Thêm `--prompt-file` cho prompt dài/nhiều dòng/có dấu |
| BUG-4 | ✅ ĐÃ SỬA | `doctor` suy `quota_capped` từ `dispatch-log.jsonl` thay vì chỉ đo `--version` |
| BUG-5 | ✅ ĐÃ SỬA | `--result-json` nuốt dòng lỗi thật của vendor — giữ N dòng cuối stderr |
| BUG-7 | ✅ ĐÃ SỬA | `--skip-git-repo-check` nằm nhầm nhánh `else` → `--cd` vào thư mục non-git luôn exit 1 |
| BUG-8 | ✅ ĐÃ SỬA | `--result-json` in JSON cho mọi đường thoát, kể cả lỗi sớm |
| BUG-9 | ✅ ĐÃ SỬA | 4 đường nuốt lỗi thật (timeout / returncode 0 / gemini / stdout) |
| BUG-10 | ✅ ĐÃ SỬA | `populate.py` báo cáo sai 2 vendor (grok, agy) |
| BUG-11 | ✅ ĐÃ SỬA | `pytest` bơm bản ghi rác vào `dispatch-log.jsonl` thật |
| BUG-1 | ⚪️ ĐÓNG | Dòng `[polykit] served:` chỉ in khi model thật KHÁC model yêu cầu — không phải bug |

---

## 🔴 CÒN MỞ

### 🔴 QUAN SÁT-3 — không có cổng chặn PII

`dispatch.py` gửi thẳng stdin ra vendor, **không kiểm tra gì**. Luật lane PGBank bắt phải qua
`pg-redact check` exit 0 trước khi gửi — nhưng chính `pg-redact` đang hỏng với văn xuôi
(xem `~/Claude/Build/tools/pg-redact/BUGS_2026-08-18.md`), nên luật đó **không thi hành được**
bằng máy, chỉ còn kỷ luật tay.
⇒ Nếu sau này vá pg-redact, đáng cân nhắc `dispatch --require-clean` gọi `pg-redact check`
làm cổng cứng. **Chưa làm bây giờ** — luật 3 lần đau, đây mới là lần 1.

### 🔴 BUG-6 — `grok` timeout rỗng khi sinh code (dsh đã GỠ OAN 20/08 chiều)

> **Trạng thái gộp**: 🔴 MỞ. Gồm 4 mục ghi dồn 19/08→20/08, nối theo thời gian.
> **Đã xong**: hiểu vì sao `stdout` rỗng khi timeout (vendor không stream, in một lần ở cuối) —
> đã thêm cờ `--stream-diagnose` + `extract_stream_text()` (sửa 20/08).
> **Còn lại**: chỉ còn `grok`. `dsh` đã được gỡ oan chiều 20/08 — xem mục cuối.

#### 19/08 — task ĐỌC FILE làm vendor timeout, `stdout` rỗng (đo trên CẢ `grok` LẪN `dsh`)

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

---

#### 20/08 — thêm bằng chứng: `grok` hỏng ở việc SINH CODE, `dsh` thì không

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

---

#### 20/08 — bớt bí: `dsh` KHÔNG stream, nên timeout không thể có output dở

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

---

#### 20/08 — nguyên nhân "stdout rỗng" + `--stream-diagnose` (sửa 20/08)

Đo 20/08 sau khi vá BUG-9, ép timeout rồi đọc `warnings`:

| Vendor | Chế độ | Bị giết sau | stdout thu được |
|---|---|---|---|
| dsh | headless (mặc định) | 25s | **0 byte** |
| grok | plain (mặc định) | 8s và 20s | **0 byte** |
| grok | `--output-format streaming-json` | 20s | **4790 byte** |

Trong 4790 byte đó: `available_commands` ×2 và **`thought` ×42**.
⇒ Vendor **đang nghĩ, không treo**. Trước đây không cách nào biết điều này.

**Kết luận**: "timeout ⇒ stdout rỗng" là hệ quả của **chế độ output không stream**, không phải
lỗi của PolyKit và cũng không phải vendor chết. PolyKit gọi CLI ở chế độ in-một-lần-ở-cuối, nên
bị giết giữa chừng thì vĩnh viễn không có gì.

**Đã làm 20/08** — cờ `--stream-diagnose`:
| Vendor | Cờ | Ghi chú |
|---|---|---|
| codex | `--json` | dùng chung với `--format json` |
| grok | `--output-format streaming-json` | đã live test, 4790 byte |
| agy | `--output-format stream-json` | cờ TOÀN CỤC, đặt trước lệnh con |
| gemini | `-o stream-json` | **chỉ lane 2**; lane 1 (agy.sh) cảnh báo rõ là chạy plain |
| dsh, claude, openrouter | — | **nói thẳng là không áp dụng**, không giả vờ |

Mặc định KHÔNG đổi. `extract_stream_text()` là hàm thuần, chịu được dòng JSON dở dang ở cuối.

**Live test** (`codex --stream-diagnose`, giết sau 25s): thu được `thread.started`,
`turn.started`, `item.completed` — thấy vendor đi tới đâu. Cùng lệnh không có cờ: chỉ có banner.

🔴 **Ba lỗi Codex review bắt được, đều là kiểu "giả vờ đã làm":**
1. `extract_stream_text` **trích nhầm log hạ tầng thành chữ trợ lý** — đo thật:
   `{"type":"item.completed","item":{"type":"error","message":"clamping SessionEnd hook..."}}`.
   ⇒ lọc theo `type`/`role`, bỏ nguyên event `error`/`tool`/`user`/`command`.
2. `--stream-diagnose --format json` **thay stdout bằng chữ đã trích** → phá hợp đồng của chính
   caller đang xin JSON. ⇒ `fmt == "json"` thì giữ nguyên JSONL thô.
3. `gemini` lane 1 (agy.sh) **không nhận cờ stream** nhưng vẫn in ghi chú chung "output là JSONL
   stream" ⇒ đúng ca GIẢ VỜ ĐÃ STREAM mà đề bài cấm. Nay lane 1 cảnh báo rõ.
   Vá chỗ này còn lòi ra ca cùng họ BUG-9(2): lane 1 khi **thành công** trả `warnings=[]` cứng,
   nuốt sạch cảnh báo — thành công không có nghĩa là không có gì để nói.

⚠️ Ghi nhận cách làm: lượt dispatch giao việc cho `dsh` **timeout ở 560s**, nhưng vì đề bài dặn
"GHI FILE SỚM" nên **file đã viết xong trước khi bị giết** — 225 test xanh dù câu trả lời cuối
không bao giờ về. Lời dặn đó không phải nghi thức.

---

## ✅ ĐÃ SỬA

### ✅ BUG-12 — `--prompt "chữ"` lặng lẽ biến thành `--prompt-file` (sửa 20/08)
**Do chính mình gây ra**: thêm `--prompt-file` (BUG-2, 19/08) mà quên argparse **mặc định cho
rút gọn tiền tố**. Từ đó `--prompt` là tiền tố duy nhất khớp `--prompt-file`, nên:
```
dispatch.py dsh --prompt "xin chào đây là văn bản"
→ blocked: không đọc được --prompt-file: [Errno 2] No such file or directory: 'xin chào đây là văn bản'
```
Lệnh đang chạy tốt bỗng gãy, và **thông báo nói về file** — người đọc đi tìm sai chỗ.
Phiên khác đã dính đúng bẫy này lúc 16:14 rồi kết luận nhầm là *"dsh/agy mất auth"*.

**Đã sửa**: `allow_abbrev=False` (chặn cả LỚP đoán-mò tiền tố, không riêng ca này) + thêm
`--prompt TEXT` thật. `--prompt` và `--prompt-file` loại trừ nhau; `--prompt` rỗng bị chặn.
**Live test**: `--prompt "Trả lời đúng một chữ: XONG"` → `status=ok`, stdout `XONG`.
`--time 30` (trước kia bị đoán thành `--timeout`) → nay `blocked: unrecognized arguments`.

### ✅ BUG-13 — nhãn `auth_unverified` nói SAI CHỖ, và vứt luôn bằng chứng (sửa 20/08)
Probe auth rớt vì lý do **không phải auth** (cờ sai, mạng, CLI đổi cú pháp) vẫn ra
`auth_unverified`, còn `error` chỉ ghi `auth_probe_unverified (exit N)` — **stderr bị vứt**.
Nhãn bảo người đọc đi kiểm auth, mà bằng chứng để cãi lại thì không còn.
Cùng họ với BUG-5/BUG-9: dòng lỗi thật bị nuốt.
**Đã sửa**: giữ 3 dòng cuối stderr (cắt 300 ký tự) vào `probe.error`.
⚠️ Ghi nhận: lúc kiểm lại 16:40 thì `agy`/`dsh` đều `ready`, `error=None` — **báo động
`auth_unverified` hôm đó KHÔNG tái hiện được**. Vá cái này là vá khuyết tật thiết kế, không phải
vá triệu chứng đã thấy.


### ✅ BUG-2 — prompt dài không có đường truyền file (đã sửa 19/08)

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

### ✅ BUG-4 — `doctor` báo `ready` cho vendor ĐANG BỊ CAP (sửa 20/08)

19/08 lúc 13:5x, đo trực tiếp trong cùng một phiên:
- `codex exec …` → `ERROR: You've hit your usage limit … try again at Aug 20th 10:58 AM`
- `gemini -p …` → `429 TerminalQuotaError: You have exhausted your daily quota`

Ngay sau đó `python3 bin/doctor.py` in **7/7 `ready`**, gồm cả `codex` và `gemini`.

⇒ `doctor` đang đo **"binary có tồn tại và chạy được `--version` không"**, chứ không đo
**"gọi được không"**. Với người dùng thì hai thứ đó khác hẳn: bảng xanh mà dispatch chết ngay.
Đây chính là điểm yếu M3 mà BACKLOG đã ghi (cap-detect dựa vào parse stderr) — nay có bằng chứng
sống thay vì suy đoán.
**Đã sửa 20/08** — `bin/lib/doctor_quota.py`, hàm THUẦN `quota_capped_since(records, now)`:
suy từ `docs`-log `dispatch-log.jsonl` đã có sẵn, không gọi mạng, không gọi CLI.
- Bản ghi **mới thắng** bản ghi cũ: `status=ok` sau `quota_capped` ⇒ cap đã hết.
- Chỉ hạ `ready → quota_capped`, **không** đụng `not_installed` / `installed_not_authed`.
- Bảng in kèm mốc bằng chứng: `-> Hết quota — bằng chứng dispatch lúc <ts>`.
- `ts` hỏng/thiếu/ở tương lai → bỏ qua bản ghi, không nổ.

🔴 **Một cửa sổ TTL chung cho mọi vendor là SAI** (Codex review chỉ ra) — ba kiểu quota khác hẳn:
| Vendor | Kiểu | Cửa sổ |
|---|---|---|
| codex, claude | hẹn mốc tuyệt đối, thường trong ngày | 5 giờ |
| gemini, agy | quota theo **NGÀY** | 24 giờ |
| grok, dsh, openrouter | **hết tiền** (402), KHÔNG tự reset | `None` — giữ tới khi có `ok` |

Để grok tự xanh lại sau 5h là **báo sai chiều nguy hiểm**: người đọc tin là gọi được rồi mới chết.

⚠️ Lỗ `read_evidence()` mặc định `limit=20`: chỉ vài lượt dispatch sau khi cap là bản ghi cap
trôi khỏi cửa sổ đọc → doctor lại xanh như chưa vá. Đã nâng `EVIDENCE_LOOKBACK = 500`.

**Live test**: grok trả 402 thật lúc 07:36 → `doctor` in `grok | quota_capped` kèm mốc bằng chứng.
Đúng ca đã hỏng hôm 19/08. 207 test xanh.

**Còn treo (Codex nêu, CHƯA làm)**: cap tính theo `vendor`, **không theo model/account/lane** —
một model free chạy `ok` có thể xoá cap của model paid. Và chưa parse mốc `try again at ...` mà
codex in ra thành `reset_at` chính xác. Chưa đủ đau để làm.

### ✅ BUG-5 — `--result-json` nuốt mất DÒNG LỖI THẬT của vendor (đã sửa 20/08)

> Bối cảnh: nhờ vendor review một bản vá Python ~11KB. Cả 2 vendor đều KHÔNG trả được kết quả,
> nhưng cách hỏng khác nhau và cả hai đều làm mất dấu vết nguyên nhân.

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

### ✅ BUG-7 — `--cd` trỏ vào thư mục KHÔNG-git → codex luôn exit 1 (ĐÃ SỬA)

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
**Trạng thái**: ✅ ĐÃ SỬA (unit test 156 passed + live test).
⚠️ Bản CÀI ở `~/.claude/plugins/cache/.../polykit/0.5.0/` VẪN CÒN LỖI cho tới lần cập nhật
plugin kế tiếp — sửa ở repo theo đúng luật, đừng vá vào bản cài.

### ✅ BUG-8 — `--result-json` KHÔNG in JSON khi lỗi sớm → caller nhận file 0 byte (đã sửa 20/08)

> **Trạng thái gộp**: ✅ ĐÃ SỬA (20/08). Gồm 2 mục ghi dồn 20/08, nối theo thời gian:
> mục đầu ghi 🟡 MỞ (có đường vòng), mục sau ghi ✅ đã vá → mục sau thắng.

#### 20/08 — phát hiện: `--result-json` in 0 byte khi lỗi sớm

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

---

#### 20/08 — đã vá, gồm cả hai chỗ rò Codex review chỉ ra thêm

`_chan_som()` in `DispatchResult(status="blocked", reason="guard_violation")` ra stdout khi có
`--result-json`, giữ **nguyên văn** thông báo lỗi trong `warnings` (danh sách model hợp lệ, gợi ý
`--allow-unknown-model`). Không có cờ thì y như cũ. Vẫn `exit 2` để script phân biệt với lỗi vendor.

Codex review chỉ ra **hai chỗ vẫn rò**, đã vá nốt:
1. **Lỗi CỜ do argparse** (vendor sai, option lạ, thiếu tham số) xảy ra **trước** khi code mình
   chạy → `exit 2`, stdout rỗng. ⇒ `_ParserRaJson.error()` soi thẳng `sys.argv` (chưa parse xong
   nên chưa có `args`) và in JSON kèm `usage` để người ta sửa được lệnh.
2. **`--doctor --result-json`** thoát với **stdout 0 byte, exit 1** — đúng cái BUG-8 đang sửa.
   ⇒ `_doctor_ra_json()`, `reason="doctor_failed"` khi không đạt.

Đo lại: vendor sai → 926B JSON · option lạ → 732B · `--doctor` → 298B. 238 test xanh.

⚠️ Ghi nhận: lần "live test đỏ" đầu tiên ở mục này là **lỗi vòng lặp shell của người kiểm**, không
phải lỗi code — chạy tách từng ca thì đúng ngay. Kiểm cái kiểm trước khi kết luận.

### ✅ BUG-9 — 4 đường nuốt lỗi thật (SỬA HẾT 20/08)

Bản vá BUG-5 chỉ chạm nhánh `returncode != 0` của `_classify_completed`. Còn:
1. ✅ **Timeout — ĐÃ SỬA 20/08.** `TimeoutExpired` mang theo `e.stdout`/`e.stderr` (phần vendor
   kịp in trước khi bị giết); trước đây vứt sạch. Nay giữ lại, bỏ echo prompt, cắt bằng
   `tail_lines`, gắn nhãn `[vendor:stdout|stderr]` vs `[polykit]`.
   `stdout` khi timeout để **RỖNG có chủ ý** — trường đó là "kết quả vendor", nhét nửa vời vào
   thì caller chỉ kiểm `stdout != ""` sẽ đọc dở dang thành kết quả thật, và JSON phình không
   giới hạn (Codex review). Phân biệt thêm 3 ca: im lặng thật · chỉ có echo prompt · có manh mối.
2. ✅ **`returncode == 0`** — nay giữ `tail_lines(stderr)` khi stderr có chữ (cảnh báo degraded /
   sắp hết quota vẫn đi kèm exit 0). stderr sạch thì `warnings=[]`, không đổ rác.
3. ✅ **`_dispatch_gemini`** — lane 1 (agy) và lane 2 (gemini-cli) nay kèm stderr thật, gắn nhãn
   `[lane N:tên]`; nhánh timeout của cả hai lane cũng gọi `_timeout_warnings`.
   ⚠️ Bẫy lúc vá: `except subprocess.TimeoutExpired:` ở hai lane này **không có `as e`** — chèn
   code dùng `e` vào là NameError lúc chạy mà test không đụng tới. Đã thêm `as e`.
4. ✅ **Vendor ghi lỗi ra stdout** — và đây là chỗ **live test bẻ gãy bản vá đầu tiên**:
   điều kiện "chỉ ngó stdout khi stderr RỖNG" nghe hợp lý nhưng sai. Đo thật với
   `codex --format json`: stderr có đúng **một dòng vô dụng** (`Reading prompt from stdin...`)
   nên guard không kích hoạt, còn lỗi 400 thật nằm trọn trong **944B stdout**.
   ⇒ exit != 0 thì **luôn** kèm stdout làm nguồn phụ (gắn nhãn `[polykit] dấu vết thêm, lấy từ
   STDOUT:`), và dò quota trên **cả hai** luồng. Live test lại: lỗi thật hiện ra.

**Bài học lặp lại lần thứ hai trong ngày**: unit test xanh không thay được live test. Cả hai lần
đều là **điều kiện guard nghe hợp lý mà sai với dữ liệu thật** (lần 1: so khớp echo prompt trượt
vì dòng trống; lần 2: "stderr rỗng" trượt vì stderr có rác).

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

### ✅ BUG-11 — chạy `pytest` bơm bản ghi vào LOG THẬT của người dùng (sửa 20/08)

**Đo được**: `wc -l` log trước/sau một lượt `pytest -q` → **+8 dòng mỗi lần**, vào
`~/Library/Application Support/polykit/dispatch-log.jsonl`. Trong đó có bản ghi mang tên vendor
THẬT: `{"vendor":"claude","status":"skipped","reason":"not_installed"}`.
Tích luỹ tới nay: **192 bản ghi `fakevendor*`** và **87 bản ghi `quota_capped` cho `claude`**.

**Vì sao mới thành nguy hiểm**: comment trong `dispatch.py` ghi *"chỉ ở CLI boundary (không ghi
khi test gọi lib)"* — đúng, nhưng nhiều test chạy `bin/dispatch.py` bằng **subprocess**, tức đi
qua đúng nhánh CLI đó. Trước BUG-4 thì log chỉ là tư liệu nên rác vô hại. **Từ khi `doctor` SUY
TRẠNG THÁI từ chính log này, rác của test có thể làm doctor nói sai về vendor thật.**
Hiện chưa gây hại thật vì `annotate_quota_capped` chỉ hạ vendor đang `ready`, mà `claude` đang
`installed_not_authed` — **thoát nhờ một luật khác, không phải nhờ thiết kế đúng.**

**Đã sửa**: `tests/conftest.py` trỏ `XDG_STATE_HOME` vào thư mục tạm ngay lúc import, nên cả
tiến trình test lẫn mọi subprocess con (thừa kế `os.environ`) đều ghi vào đó.
Kiểm lại: `pytest -q` → log thật **+0 dòng**. `tests/test_bug11_test_khong_ban_log_that.py` khoá
hành vi; đã chứng minh test không rỗng ruột (bỏ cô lập thì đường dẫn trỏ về thư mục thật).

⚠️ **CHƯA dọn 279 bản ghi rác cũ** — cố ý. Xoá dữ liệu là việc một chiều, và luật "không mất dữ
liệu > sạch đẹp" đứng trước. Muốn dọn thì lọc ra file backup rồi mới ghi đè, đừng xoá thẳng.

---

## ⚪️ ĐÓNG (không phải bug)

### ⚪️ BUG-1 — dòng `[polykit] served:` không in ra stderr → **KHÔNG phải bug** (đóng 19/08)

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

---

## Ghi chú phiên (không phải bug)

> **Bối cảnh 18/08** — Dispatch thật: soát chéo 1 bộ hồ sơ tín dụng, prompt 37.073 byte (5 file Word đã thay PII).
> Lệnh: `cat full_prompt.txt | python3 bin/dispatch.py codex gpt-5.5 --timeout 580 --result-json`

### ✅ Chạy đúng — kết quả tốt

`status=ok`, `exit_code=0`, `vendor=codex`, `model=gpt-5.5`, `served_model=gpt-5.5`, `warnings=[]`.
Nội dung: **8 phát hiện, hội tụ 4/4 lỗi chính** mình đã tự bắt (số tiền 450 vs 300, lãi suất
9,9% vs 12%, mục đích copy nhầm hồ sơ, số HĐTC cụt) — **0 ảo giác**, đúng định dạng yêu cầu.
Chi phí ~1 lượt codex thay vì tự đọc lại 5 file bằng model chính. **Đây là ca dùng đúng của PolyKit.**

### ⏱️ Số liệu

- Prompt 37 KB · timeout đặt 580s (trần cứng 600s vẫn đúng như memory ghi) · chạy trọn, không chạm trần.

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


---

#### 20/08 chiều — `dsh` KHÔNG treo: nó LÀM XONG, chỉ là lâu hơn trần 600s

Bốn phép đo mới, cùng ngày, cùng khung dispatch:

| Việc | Vendor | Qua PLK? | Kết quả |
|---|---|---|---|
| Tự mở 3 file, đếm `def` | codex | có, 60s | ✅ ok, số **khớp `grep -c '^def '`** |
| Tự mở 3 file, đếm `def` | dsh | có, 240s | ✅ ok trong **21s** |
| Đọc 1 file, phân tích 5 điểm yếu, ghi ra file | dsh | **KHÔNG** (chạy thẳng, bỏ trần) | ✅ ok trong **159s** |
| Dựng `--stream-diagnose` (sửa 3 file + viết test) | dsh | có, 560s | ⏱️ timeout — **nhưng 225 test xanh** |
| Dọn lại `docs/BUGS.md` (445→486 dòng) | dsh | có, 560s | ⏱️ timeout — **nhưng file đã viết xong, 0 nội dung mất** |

🔑 **Hai lượt timeout cuối đã LÀM XONG VIỆC.** File đã ghi đầy đủ, test xanh, kiểm chéo không mất
dữ liệu. Chỉ có **câu trả lời cuối** là không kịp về trước khi bị giết.

⇒ Với `dsh`, "timeout + `stdout` rỗng" **KHÔNG phải treo**. Nó là ba thứ cộng lại:
1. việc lớn nhiều bước cần > 560s;
2. `dsh --profile headless` **chỉ in một lần ở cuối** (không stream) → bị giết giữa chừng là 0 byte;
3. trần cứng `--timeout` của PolyKit là **600s**, không nới được.

**Đổi cách dùng ngay** (đã kiểm chứng 2/2 lần hôm nay):
- Giao việc lớn cho `dsh` thì **luôn dặn "GHI FILE SỚM"** trong đề bài. Lời dặn đó không phải
  nghi thức — nó là thứ duy nhất còn lại khi hết giờ.
- Gặp `status=timeout` từ `dsh`: **đi kiểm file trước khi kết luận thất bại** (`git status`,
  chạy test). Rất có thể việc đã xong.
- Việc quá lớn thì chạy `dsh` **thẳng, không qua PLK**, để thoát trần 600s.

**Còn lại đúng một câu hỏi**: vì sao `grok` timeout rỗng **4/4 lần** ở việc sinh code, trong khi
`dsh` cùng khung thì xong. Chưa có phép đo mới cho `grok` vì nó đang `quota_capped` (402).
Ghi nhận một manh mối chưa kiểm: 20/08 `grok` **từ chối** một việc và tự trích luật *"≤30 dòng/lượt"*
— tức nó có đọc `~/CLAUDE.md` của Tuan. Chưa rõ có liên quan không, **không đoán tiếp**.

---

## 📊 Bench codex model × effort (20/08/2026)

Bài có đáp án kiểm được: file tính lãi vay cài sẵn **5 lỗi**, đếm số lỗi nêu đúng tên hàm.
Đo bằng `codex exec --json` → event `turn.completed` mang `usage` đầy đủ.

**Trục EFFORT** (trên `gpt-5.6-terra`, mặc định cũ):

| Effort | Giây | reasoning tok | Tìm |
|---|---|---|---|
| minimal | 7 | 0 | **0/5** — trả RỖNG, đừng dùng |
| **low** | 21 | **366** | **3/5** |
| medium | 23 | 515 | 2/5 |
| high | 33 | 664 | 2/5 |

🔴 **Effort cao ĐỐT NHIỀU HƠN mà tìm ÍT HƠN.** high vs low: +81% reasoning, chậm hơn 57%, kém hơn.
Mà `codex` mặc định chạy **`medium`** và PolyKit trước đây **không ghim effort** → đang ở ô tệ nhất.

**Trục MODEL** (đều ở `low`):

| Model | reasoning tok | Tìm |
|---|---|---|
| gpt-5.4-mini | **215** | 3/5 |
| **gpt-5.5** | **246** | 3/5 |
| gpt-5.6-terra (lặp) | 321 | 3/5 |
| gpt-5.6-sol | 358 | 3/5 |
| gpt-5.6-terra | 366 | 3/5 |

⇒ **Model không tạo khác biệt chất lượng** ở low — cả 5 đều 3/5. Chênh nhau chỉ ở giá.

**Trần chung 3/5**: **0/8 lượt** bắt được `lai_don` (không kiểm ngày âm) và `qua_han` (hệ số phạt
1.5 hardcode). Hai lỗi đó là **nghiệp vụ ngân hàng**, không phải lỗi kỹ thuật.
⇒ Giao codex phần kỹ thuật; phần domain vẫn phải người đọc.

**Phát hiện phụ**: mỗi lượt tốn **~24.000 input token** overhead (system prompt + skills) DÙ prompt
chỉ 1 dòng. Việc nhỏ vẫn trả phí lớn → gộp việc thay vì bắn nhiều lượt vụn.

**Đã đổi**: `default_model` codex `gpt-5.6-terra` → **`gpt-5.5`**, và PolyKit **ghim
`-c model_reasoning_effort=low`** (codex không có cờ `--effort`).

⚠️ **Giới hạn của bench này**: 1 mẫu mỗi ô (terra/low 2 mẫu), **1 bài**. Đủ để nói *"không có bằng
chứng effort cao tốt hơn"* — **chưa đủ** để nói medium/high chắc chắn tệ hơn. Muốn chắc thì chạy
thêm 2-3 bài khác loại.

### ✅ BUG-14 — `populate.py` quên mất vai HARNESS, chỉ nghĩ vai VENDOR (sửa 20/08)
Câu hỏi của Tuan *"populate cho tất cả harness dùng chưa"* lộ ra một nhầm lẫn vai:
- **Vendor** = thứ PolyKit **gọi đi** (dispatch target)
- **Harness** = thứ Tuan **ngồi làm việc trong đó**, cần gọi PolyKit

`dsh` là **cả hai**, nhưng `populate.py` chỉ phủ vai vendor. Đếm thật trên máy: **5/9** harness
được phủ. Thiếu `dsh`, `goose`, `zeroclaw`, `opencode` — tất cả đều CÓ cơ chế skill/plugin.

**Đã làm**: thêm đích `~/.agents/skills/polykit/SKILL.md` — gốc skill dùng chung mà `dsh` quét
(theo README của `@deepseek-ai/dsh-skill-filesystem`: `agentsHome` mặc định `~/.agents`).

🔴 **Bẫy bắt được bằng live test**: lần ghi đầu đặt sai tầng
(`polykit/dispatch/SKILL.md` thay vì `polykit/SKILL.md`). `--apply` vẫn báo *"ghi 4 file"* rất
gọn gàng, nhưng hỏi `dsh` thì nó trả lời **"không có skill nào tên polykit"**.
⇒ **Ghi được file KHÔNG có nghĩa là harness đọc được.** Đích populate mới nào cũng phải hỏi
chính harness đó một câu, đừng tin dòng "đã ghi N file".
Live test sau khi sửa: `dsh` trích đúng lệnh dispatch và đúng luật cấm sửa tay.

**Còn treo**: `goose` (`~/.config/goose/skills`), `zeroclaw` (`zeroclaw skills`), `opencode`
(`agent`/`mcp`) — chưa phủ. Cố ý chờ: memory ghi 3 cái này *"cài để xem UI, chưa test tử tế"*,
chưa phải lane làm việc thật (luật 3 lần đau).
