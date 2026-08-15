# -*- coding: utf-8 -*-
import json
items = json.load(open('data_jina2/lore_toc.json', encoding='utf-8'))['items']
# 只输出 level>0 的标题，缩进表示层级
lines = []
for it in items:
    lv = it['level']
    if lv > 0:
        indent = '  ' * (lv - 1)
        prefix = {1: '[一级] ', 2: '[二级] ', 3: '[三级] '}.get(lv, '')
        lines.append(f"{indent}{prefix}{it['text']}")
with open('data/lore_toc_目录.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('已导出', len(lines), '条目录 -> data/lore_toc_目录.txt')
# 统计
from collections import Counter
c = Counter(it['level'] for it in items if it['level']>0)
print('层级统计:', dict(c))
