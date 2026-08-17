#!/bin/bash
cd ~/Developer/polykit || exit 1
S=TRANG-THAI-VONG2.md
echo "# Vòng 2 — vá 4 lỗi · bắt đầu $(date '+%H:%M %d/%m')" > $S
echo "## 1. MAKER — agy @ claude-opus-4-6-thinking" >> $S
agy --model claude-opus-4-6-thinking --print-timeout 25m --dangerously-skip-permissions \
    --print "Đọc file ~/Developer/polykit/DE-BAI-VA-VONG2.md và thực hiện đúng toàn bộ yêu cầu trong đó." > .maker2.out 2> .maker2.err
echo "- exit=$? · báo cáo: $([ -f BAO-CAO-VA-VONG2.md ] && wc -l < BAO-CAO-VA-VONG2.md || echo 'KHÔNG CÓ') dòng · $(date '+%H:%M')" >> $S
echo "## 2. QA — Grok" >> $S
grok --permission-mode bypassPermissions --prompt-file ./DE-BAI-DAP-VONG2.md > .qa2.out 2> .qa2.err
echo "- exit=$? · báo cáo: $([ -f DAP-VONG2.md ] && wc -l < DAP-VONG2.md || echo 'KHÔNG CÓ') dòng · $(date '+%H:%M')" >> $S
echo "## 3. Kiểm tự động (không do AI làm)" >> $S
git diff --quiet config/vendors.json && echo "- ✅ vendors.json KHÔNG bị đụng" >> $S || echo "- 🔴 vendors.json BỊ SỬA — phá ràng buộc cứng" >> $S
echo "- JSON hợp lệ: $(python3 -c 'import json;json.load(open("config/vendors.json"));print("OK")' 2>&1|tail -1)" >> $S
echo "- test: $(~/.pyenv/versions/3.11.8/bin/python -m pytest tests/ -q 2>&1|tail -1)" >> $S
echo "" >> $S; echo "XONG $(date '+%H:%M %d/%m')" >> $S
