# -*- coding: utf-8 -*-
"""测试集校准：对每题核心实体词做全库 BM25，取 top-3 章节作为期望命中（专名命中可靠）。
输出 data/testset.json，供 eval_grid.py 使用。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import DATA_DIR  # noqa: E402
from app.rag import Store, bigram_tokens  # noqa: E402

# (问题, 核心实体词)
QS = [
    ("白玉蛊是怎么炼成的", "白玉蛊"),
    ("爱生离怎么炼制", "爱生离"),
    ("月光蛊有什么能力", "月光蛊"),
    ("熊力蛊是什么", "熊力蛊"),
    ("溪流蛊是什么", "溪流蛊"),
    ("监天塔是什么", "监天塔"),
    ("成尊的四个条件", "成尊"),
    ("幽魂魔尊是谁", "幽魂魔尊"),
    ("春秋蝉有什么能力", "春秋蝉"),
    ("方源怎么得到酒虫", "酒虫"),
    ("月霓裳蛊是谁用的", "月霓裳"),
    ("赤铁舍利蛊是什么", "赤铁舍利蛊"),
    ("石窍蛊的作用", "石窍蛊"),
    ("巨阳仙尊是谁", "巨阳仙尊"),
    ("星宿仙尊是谁", "星宿仙尊"),
    ("方源什么时候得到春秋蝉", "春秋蝉"),
    ("古月方正和方源什么关系", "方正"),
    ("青茅山是什么地方", "青茅山"),
    ("白凝冰用的是什么道", "白凝冰"),
    ("中洲有哪些势力", "中洲"),
    ("北原黄金家族是什么", "黄金家族"),
    ("方源最后成尊了吗", "成尊"),
    ("爱情蛊在哪里讲", "爱情蛊"),
    ("盗天魔尊是谁", "盗天魔尊"),
    ("影宗是什么组织", "影宗"),
    ("月旋蛊怎么来的", "月旋蛊"),
    ("魂道是什么", "魂道"),
    ("方源在擂台上打败了谁", "擂台"),
    ("古月一族在哪", "古月一族"),
    ("一转酒虫怎么炼", "酒虫"),
]

novel = Store(os.path.join(str(DATA_DIR), "novel"))
cases = []
for q, kw in QS:
    scores = novel.bm25.get_scores(bigram_tokens(kw))
    top = [int(i) for i in sorted(range(novel.n), key=lambda i: -scores[i])[:4] if scores[int(i)] > 0]
    gts = []
    seen = set()
    for i in top:
        m = novel.meta[i]
        key = (m["vol"], m["chapter"])
        if key in seen:
            continue
        seen.add(key)
        gts.append([m["vol"][:6], [m["chapter"]]])
    cases.append({"q": q, "kw": kw, "expect": gts})
    print(f"{q:20s} [{kw}] -> {gts}")

with open(os.path.join(str(DATA_DIR), "testset.json"), "w", encoding="utf-8") as f:
    json.dump({"cases": cases}, f, ensure_ascii=False, indent=1)
print("\nsaved -> data/testset.json")
