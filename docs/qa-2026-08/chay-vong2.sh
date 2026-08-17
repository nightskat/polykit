#!/bin/bash
cd ~/Developer/polykit || exit 1
S=TRANG-THAI-VONG2.md
echo "# Vòng 2 — vá 4 lỗi · bắt đầu $(date '+%H:%M %d/%m')" > $S

# MAKER — thử tối đa 3 lần, vì agy có thể nuốt prompt hoặc dừng sớm
for i in 1 2 3; do
  echo "## MAKER lần $i — agy @ claude-opus-4-6-thinking ($(date '+%H:%M'))" >> $S
  agy --model gemini-3.1-pro-high --print-timeout 25m --dangerously-skip-permissions \
      --print "Đọc file ~/Developer/polykit/DE-BAI-VA-VONG2.md và thực hiện đúng toàn bộ yêu cầu trong đó. Bắt buộc GHI FILE BAO-CAO-VA-VONG2.md ngay sau khi vá xong lỗi đầu tiên." > .maker2.out 2> .maker2.err
  n=$([ -f BAO-CAO-VA-VONG2.md ] && wc -l < BAO-CAO-VA-VONG2.md || echo 0)
  echo "- exit=$? · out=$(wc -c < .maker2.out) byte · báo cáo=$n dòng · $(date '+%H:%M')" >> $S
  [ "$n" -gt 10 ] && { echo "- ✅ có báo cáo, dừng thử lại" >> $S; break; }
  echo "- ⚠️ chưa ra báo cáo, thử lại" >> $S
done

echo "## QA — Grok ($(date '+%H:%M'))" >> $S
grok --permission-mode bypassPermissions --prompt-file ./DE-BAI-DAP-VONG2.md > .qa2.out 2> .qa2.err
echo "- exit=$? · báo cáo=$([ -f DAP-VONG2.md ] && wc -l < DAP-VONG2.md || echo 0) dòng · $(date '+%H:%M')" >> $S

echo "## Kiểm tự động (không do AI làm)" >> $S
git diff --quiet config/vendors.json && echo "- ✅ vendors.json KHÔNG bị đụng" >> $S || echo "- 🔴 vendors.json BỊ SỬA — phá ràng buộc cứng" >> $S
echo "- JSON hợp lệ: $(python3 -c 'import json;json.load(open("config/vendors.json"));print("OK")' 2>&1|tail -1)" >> $S
echo "- test: $(~/.pyenv/versions/3.11.8/bin/python -m pytest tests/ -q 2>&1|tail -1)" >> $S
echo "- code đã đổi: $(git diff --stat bin/ | tail -1)" >> $S
echo "" >> $S; echo "XONG $(date '+%H:%M %d/%m')" >> $S
