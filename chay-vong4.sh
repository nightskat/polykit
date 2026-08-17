#!/bin/bash
cd ~/Developer/polykit || exit 1
S=TRANG-THAI-VONG4.md; P=~/.pyenv/versions/3.11.8/bin/python
echo "# Vòng 4 · bắt đầu $(date '+%H:%M %d/%m')" > $S
for i in 1 2 3; do
  echo "## MAKER lần $i — agy @ gemini-3.1-pro-high ($(date '+%H:%M'))" >> $S
  agy --model gemini-3.1-pro-high --print-timeout 25m --dangerously-skip-permissions \
      --print "Đọc file ~/Developer/polykit/DE-BAI-VONG4.md và thực hiện đúng toàn bộ yêu cầu trong đó. GHI FILE BAO-CAO-VONG4.md ngay sau khi vá xong lỗi đầu tiên." > .m4.out 2> .m4.err
  n=$([ -f BAO-CAO-VONG4.md ] && wc -l < BAO-CAO-VONG4.md || echo 0)
  echo "- exit=$? · out=$(wc -c < .m4.out) byte · báo cáo=$n dòng · $(date '+%H:%M')" >> $S
  [ "$n" -ge 5 ] && { echo "- ✅ có báo cáo" >> $S; break; }
  echo "- ⚠️ chưa ra báo cáo, thử lại" >> $S
done
echo "## Cổng chặn — không do AI làm" >> $S
T=$($P -m pytest tests/ -q 2>&1|tail -1); echo "- test: $T" >> $S
echo "- 11 vendor dump-config với model mặc định:" >> $S
FAIL=0
for v in agy dsh grok codex gemini claude opencode goose zeroclaw jules openrouter; do
  $P bin/dispatch.py $v --dump-config >/dev/null 2>&1
  c=$?; [ $c -ne 0 ] && { echo "  - 🔴 $v EXIT $c" >> $S; FAIL=$((FAIL+1)); }
done
[ $FAIL -eq 0 ] && echo "  - ✅ cả 11 exit 0" >> $S || echo "  - 🔴 $FAIL/11 VẪN HỎNG" >> $S
case "$T" in *failed*) echo "- 🔴 TEST ĐỎ → không gọi QA" >> $S; echo "XONG $(date '+%H:%M')" >> $S; exit 0;; esac
[ $FAIL -ne 0 ] && { echo "- 🔴 vendor còn hỏng → không gọi QA" >> $S; echo "XONG $(date '+%H:%M')" >> $S; exit 0; }
echo "## QA — Grok ($(date '+%H:%M'))" >> $S
grok --permission-mode bypassPermissions --prompt-file ./DE-BAI-DAP-VONG4.md > .q4.out 2> .q4.err
echo "- exit=$? · báo cáo=$([ -f DAP-VONG4.md ] && wc -l < DAP-VONG4.md || echo 0) dòng · $(date '+%H:%M')" >> $S
echo "- test sau QA: $($P -m pytest tests/ -q 2>&1|tail -1)" >> $S
echo "" >> $S; echo "XONG $(date '+%H:%M %d/%m')" >> $S
