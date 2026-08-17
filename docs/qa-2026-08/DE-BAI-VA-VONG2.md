# ĐỀ BÀI — Vá 4 lỗi QA tìm ra (vòng 2)

Repo `~/Developer/polykit`. Đọc `DAP-DISPATCH-V2.md` (báo cáo QA) và `DE-BAI-DISPATCH-V2.md` (spec gốc) trước.
QA đã chạy lệnh thật và bắt được 4 chỗ. **Cả 4 đều đúng, không cãi.**

## Vá theo thứ tự thiệt hại

### 1. 🔴 `--doctor` nuốt lỗi, luôn báo OK, exit 0
Bằng chứng QA:
```
bin/dispatch.py agy --doctor
  stderr: /bin/sh: /model: No such file or directory
  stderr: /bin/sh: /usage: No such file or directory
  stdout: [polykit] doctor: agy OK        ← SAI
  EXIT 0                                   ← SAI
bin/dispatch.py dsh --doctor
  stderr: error: --profile <name> is required (×2)
  stdout: [polykit] doctor: dsh OK         ← SAI
```
**Hai lỗi gốc:**
- `zero_quota_cmds` của agy là **lệnh nội bộ của CLI đó** (`/model`, `/usage`), KHÔNG phải lệnh shell. Với agy phải gọi `agy -p "/model"`. Với codex/dsh thì `zero_quota_cmds` mới là lệnh shell đầy đủ.
- `dsh --dump-config` thiếu `--profile headless`. `verify_cmd` trong JSON ghi thiếu → **đừng sửa JSON**, hãy xử lý ở code hoặc báo lỗi rõ.

**Yêu cầu:** `--doctor` phải trả **exit khác 0** khi lệnh kiểm thất bại, và **in nguyên văn lỗi ra stderr**, không nuốt. Đây là lỗi nặng nhất: một khâu gác cổng chết im lặng còn tệ hơn không có khâu nào.

### 2. 🔴 `openrouter` biến mất khỏi CLI
Có trong REGISTRY cũ, không có trong `vendors.json` v2 → `invalid choice: 'openrouter'`, exit 2. Lane cũ gãy.
**Yêu cầu:** giữ `openrouter` chạy được. Nếu cần dữ liệu vendor thì đọc từ REGISTRY cũ và **ghi rõ trong báo cáo là nó chưa có trong JSON v2** — nêu ra, đừng tự thêm vào JSON.

### 3. 🔴 "Thêm vendor = sửa JSON" chưa đạt
`opencode`/`goose`/`zeroclaw`/`jules` vào được `choices` nhưng dispatch vẫn `if/elif` cứng → `status=blocked reason=unknown_vendor`, exit 1.
**Yêu cầu:** dựng lệnh từ dữ liệu JSON (`headless`, `model_flag`, `auto_approve`, `workdir_flag`). Vendor nào **thiếu trường bắt buộc** thì báo lỗi **nói rõ thiếu trường nào**, không báo `unknown_vendor`.

### 4. 🟠 Model bịa vẫn được nhận
`dsh totally-fake-model --dump-config` → nhận, exit 0.
**Yêu cầu:** model không nằm trong `models` của vendor đó → **từ chối, exit 2**, in danh sách model hợp lệ. Có cờ `--allow-unknown-model` để vượt qua khi cần.

## Ràng buộc CỨNG
1. 🔴 **KHÔNG sửa `config/vendors.json`.** Kiểm bằng `git diff --quiet config/vendors.json` — phải sạch. Thiếu gì thì **nêu trong báo cáo**.
2. 🔴 Không thêm dependency ngoài stdlib + `requirements.txt` hiện có.
3. Test cũ xanh nguyên. Thêm test cho **cả 4 lỗi trên** — mỗi lỗi ít nhất 1 test, **khẳng định hành vi ĐÚNG**, không phải khẳng định "có chạy".
4. Đọc file cùng thư mục trước khi viết, theo đúng lối cấu trúc sẵn có.
5. Cấm mở `~/Work/`, `~/Claude/Projects/`, `~/Data/`, `~/Downloads/`; cấm `.pdf .jpg .png .xlsx .docx .csv`.

## 🔴 LIVE BEFORE CLAIM
Báo cáo phải có mục **"Lệnh đã chạy"** liệt kê **nguyên văn** lệnh + **output thật** + **mã thoát thật**, cho ít nhất:
- `--doctor` của **agy** và **dsh** (chứng minh giờ không còn báo OK giả)
- một lượt `dsh --dump-config` (0 token) chứng minh vẫn ghim `deepseek-v4-pro`
- một ca model bịa bị từ chối
- `git diff --quiet config/vendors.json; echo $?` → phải in `0`

⚠️ QA sẽ **chạy lại đúng những lệnh bạn khai**. Phiên 17/08 đã bắt hai vụ khai khống theo đúng cách đó.

## Trả lời
- Ghi `BAO-CAO-VA-VONG2.md`, tiếng Việt, **≤50 dòng**, bảng phẳng.
- **Ghi file ngay khi vá xong lỗi đầu tiên**, cập nhật dần.
- Không mở bài, không khen.
