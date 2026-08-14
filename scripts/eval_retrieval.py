# -*- coding: utf-8 -*-
"""检索评估：测试集 + hit@k，用于调优 RAG_TOP_K。
用法：python scripts/eval_retrieval.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import DATA_DIR, MODEL_CACHE  # noqa: E402
from app.rag import Retriever  # noqa: E402

# (问题, 期望命中 [(store, 卷关键字或None, 章号或None), ...])
CASES = [
    ("白玉蛊是怎么炼成的", [("novel", "第1卷", 100)]),
    ("爱生离是什么蛊 怎么炼制", [("novel", "第1卷", 75), ("novel", "第1卷", 76)]),
    ("月光蛊有什么能力", [("novel", "第1卷", 62)]),
    ("方源和方正擂台比武", [("novel", "第1卷", 83), ("novel", "第1卷", 82)]),
    ("熊力蛊和溪流蛊是什么", [("novel", "第1卷", 22)]),
    ("监天塔是什么", [("novel", "第4卷", 356), ("novel", "第4卷", 357), ("novel", "第4卷", 360)]),
    ("成尊的四个条件", [("novel", "第6卷", 119)]),
    ("幽魂魔尊是什么人", [("novel", "第6卷", 81)]),
    ("人祖传讲的是什么", [("lore", None, None)]),
    ("十大尊者都有谁", [("lore", None, None)]),
    ("真元 仙元 九转境界", [("lore", None, None)]),
    ("方源转世重生五百年前", [("novel", "第1卷", 99)]),
    ("仙蛊屋有哪些", [("lore", None, None)]),
    ("青茅山是什么地方", [("novel", "第1卷", None)]),
    ("蛊真人这本书的作者是谁", [("lore", None, None)]),
]


def main():
    r = Retriever(DATA_DIR, MODEL_CACHE, top_k=8)
    print(f"stores: { {n: s.n for n, s in r.stores.items()} }  model: {r.model_name}\n")
    for k in (3, 5, 8):
        hit_n = 0
        print(f"===== hit@{k} =====")
        for q, expect in CASES:
            hits = r.search(q, k=k)
            ok = any(
                any(
                    h.get("type") == st
                    and (vol_kw is None or vol_kw in h.get("vol", ""))
                    and (ch is None or h.get("chapter") == ch)
                    for h in hits
                )
                for st, vol_kw, ch in expect
            )
            hit_n += int(ok)
            print(f"  {'OK ' if ok else 'XX '} {q}")
        print(f"  => hit@{k}: {hit_n}/{len(CASES)} = {hit_n / len(CASES):.0%}\n")

    print("===== 样例 top-5 人工检查 =====")
    for q, _ in CASES[:6]:
        print(f"\nQ: {q}")
        for i, h in enumerate(r.search(q, k=5), 1):
            if h.get("type") == "lore":
                print(f"  {i}. [设定] {h.get('section') or h.get('title')}  ({len(h.get('text') or '')}字)")
            else:
                print(f"  {i}. [正文] {h.get('vol')} 第{h.get('chapter')}章 {h.get('title')}")


if __name__ == "__main__":
    main()
