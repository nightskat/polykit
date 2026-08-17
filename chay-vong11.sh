#!/bin/bash
cd ~/Developer/polykit || exit 1
S=TRANG-THAI-VONG11.md; P=~/.pyenv/versions/3.11.8/bin/python
echo "# Vòng 4 · bắt đầu $(date '+%H:%M %d/%m')" > $S
for i in 1 2 3; do
  echo "## MAKER lần $i — agy @ gemini-3.1-pro-high ($(date '+%H:%M'))" >> $S
  agy --model gemini-3.1-pro-high --print-timeout 25m --dangerously-skip-permissions \
      --print "Đọc file ~/Developer/polykit/DE-BAI-VONG11.md và thực hiện đúng toàn bộ yêu cầu trong đó. GHI FILE BAO-CAO-VONG11.md ngay sau khi vá xong lỗi đầu tiên." > .m11.out 2> .m11.err
  n=$([ -f BAO-CAO-VONG11.md ] && wc -l < BAO-CAO-VONG11.md || echo 0)
  echo "- exit=$? · out=$(wc -c < .m11.out) byte · báo cáo=$n dòng · $(date '+%H:%M')" >> $S
  [ "$n" -ge 5 ] && { echo "- ✅ có báo cáo" >> $S; break; }
  echo "- ⚠️ chưa ra báo cáo, thử lại" >> $S
done
echo "## Cổng chặn — không do AI làm" >> $S
T=$($P -m pytest tests/ -q 2>&1|tail -1); echo "- test: $T" >> $S
grep -q "dry-run" commands/failover.md && echo "- ✅ commands/failover.md CÓ --dry-run" >> $S || { echo "- 🔴 THIẾU --dry-run -> plugin gửi THẬT" >> $S; FAILDRY=1; }
echo "- 7 vendor dump-config với model mặc định:" >> $S
FAIL=0
for v in agy dsh grok codex gemini claude openrouter; do
  $P bin/dispatch.py $v --dump-config >/dev/null 2>&1
  c=$?; [ $c -ne 0 ] && { echo "  - 🔴 $v EXIT $c" >> $S; FAIL=$((FAIL+1)); }
done
[ $FAIL -eq 0 ] && echo "  - ✅ cả 7 exit 0" >> $S || echo "  - 🔴 $FAIL/7 VẪN HỎNG" >> $S
[ "${FAILDRY:-0}" = "1" ] && { echo "- 🔴 thiếu --dry-run -> không gọi QA" >> $S; echo "XONG $(date '+%H:%M')" >> $S; exit 0; }
case "$T" in *failed*) echo "- 🔴 TEST ĐỎ → không gọi QA" >> $S; echo "XONG $(date '+%H:%M')" >> $S; exit 0;; esac
[ $FAIL -ne 0 ] && { echo "- 🔴 vendor còn hỏng → không gọi QA" >> $S; echo "XONG $(date '+%H:%M')" >> $S; exit 0; }
echo "## QA — Grok ($(date '+%H:%M'))" >> $S
grok --permission-mode bypassPermissions --prompt-file ./DE-BAI-DAP-VONG11.md > .q11.out 2> .q11.err
echo "- exit=$? · báo cáo=$([ -f DAP-VONG11.md ] && wc -l < DAP-VONG11.md || echo 0) dòng · $(date '+%H:%M')" >> $S
echo "- test sau QA: $($P -m pytest tests/ -q 2>&1|tail -1)" >> $S
echo "" >> $S; echo "XONG $(date '+%H:%M %d/%m')" >> $S
