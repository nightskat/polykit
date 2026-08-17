#!/bin/bash
# Dây chuyền tự hành: maker (agy@Opus) → QA (Grok) → ghi trạng thái.
# Chạy tuần tự, mỗi bước ghi log riêng. Không cần người trông.
cd ~/Developer/polykit || exit 1
S=TRANG-THAI-DAY-CHUYEN.md
echo "# Dây chuyền dispatch v2 — bắt đầu $(date '+%H:%M %d/%m')" > $S

echo "## 1. MAKER — agy @ claude-opus-4-6-thinking" >> $S
agy --model claude-opus-4-6-thinking --print-timeout 25m --dangerously-skip-permissions \
    --print "Đọc file ~/Developer/polykit/DE-BAI-DISPATCH-V2.md và thực hiện đúng toàn bộ yêu cầu trong đó." \
    > .maker.out 2> .maker.err
echo "- exit=$? · báo cáo: $([ -f BAO-CAO-DISPATCH-V2.md ] && wc -l < BAO-CAO-DISPATCH-V2.md || echo 'KHÔNG CÓ') dòng · xong $(date '+%H:%M')" >> $S

echo "## 2. QA — Grok (khác họ maker)" >> $S
grok --permission-mode bypassPermissions --prompt-file ./DE-BAI-DAP-DISPATCH-V2.md \
    > .qa.out 2> .qa.err
echo "- exit=$? · báo cáo: $([ -f DAP-DISPATCH-V2.md ] && wc -l < DAP-DISPATCH-V2.md || echo 'KHÔNG CÓ') dòng · xong $(date '+%H:%M')" >> $S

echo "## 3. Kiểm tự động (không tin báo cáo)" >> $S
echo "- vendors.json có bị sửa không: $(git diff --stat config/vendors.json | wc -l | tr -d ' ') dòng thay đổi (0 = KHÔNG ĐỘNG, đúng)" >> $S
echo "- JSON còn hợp lệ: $(python3 -c 'import json;json.load(open("config/vendors.json"));print("OK")' 2>&1 | tail -1)" >> $S
echo "- git status:" >> $S; git status --short >> $S
echo "" >> $S; echo "XONG LÚC $(date '+%H:%M %d/%m')" >> $S
