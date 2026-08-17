#!/bin/bash
cd ~/Developer/polykit || exit 1
S=TRANG-THAI-VONG3.md
P=~/.pyenv/versions/3.11.8/bin/python
echo "# Vòng 3 — sửa lược đồ + code · bắt đầu $(date '+%H:%M %d/%m')" > $S
for i in 1 2 3; do
  echo "## MAKER lần $i — agy @ gemini-3.1-pro-high ($(date '+%H:%M'))" >> $S
  agy --model gemini-3.1-pro-high --print-timeout 25m --dangerously-skip-permissions \
      --print "Đọc file ~/Developer/polykit/DE-BAI-VONG3.md và thực hiện đúng toàn bộ yêu cầu trong đó. GHI FILE BAO-CAO-VONG3.md ngay sau khi vá xong lỗi đầu tiên." > .m3.out 2> .m3.err
  n=$([ -f BAO-CAO-VONG3.md ] && wc -l < BAO-CAO-VONG3.md || echo 0)
  echo "- exit=$? · out=$(wc -c < .m3.out) byte · báo cáo=$n dòng · $(date '+%H:%M')" >> $S
  [ "$n" -gt 10 ] && { echo "- ✅ có báo cáo" >> $S; break; }
  echo "- ⚠️ chưa ra báo cáo, thử lại" >> $S
done
echo "## Kiểm chặn TRƯỚC khi gọi QA (không do AI làm)" >> $S
T=$($P -m pytest tests/ -q 2>&1|tail -1); echo "- test: $T" >> $S
echo "- JSON hợp lệ: $($P -c 'import json;json.load(open("config/vendors.json"));print("OK")' 2>&1|tail -1)" >> $S
echo "- schema: v$($P -c 'import json;print(json.load(open("config/vendors.json"))["schema_version"])' 2>&1|tail -1)" >> $S
case "$T" in *failed*) echo "- 🔴 CÓ TEST ĐỎ → không gọi QA, cần vá lại" >> $S; echo "XONG $(date '+%H:%M')" >> $S; exit 0;; esac
echo "## QA — Grok (khác họ maker) ($(date '+%H:%M'))" >> $S
grok --permission-mode bypassPermissions --prompt-file ./DE-BAI-DAP-VONG3.md > .q3.out 2> .q3.err
echo "- exit=$? · báo cáo=$([ -f DAP-VONG3.md ] && wc -l < DAP-VONG3.md || echo 0) dòng · $(date '+%H:%M')" >> $S
echo "- test lại sau QA: $($P -m pytest tests/ -q 2>&1|tail -1)" >> $S
echo "" >> $S; echo "XONG $(date '+%H:%M %d/%m')" >> $S
