# -*- coding: utf-8 -*-
"""多模型对比评估：只计正文库命中（设定库命中不算）。
用法：python scripts/eval_models.py [--data data --name 模型名 ...]  （不传则跑全部可用库）
"""
import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.embed import BgeM3Embedder  # noqa: E402
from app.rag import Store, bigram_tokens  # noqa: E402

# 测试集：从设定合集 docx 反推的问题；期望命中 = (卷名关键字, [章号...])，命中任意即算
CASES = [
    ("白玉蛊怎么炼成", [("第1卷", [98, 99, 100])]),
    ("爱生离怎么炼制", [("第1卷", [75, 76])]),
    ("月光蛊有什么能力", [("第1卷", [62, 22])]),
    ("熊力蛊是什么", [("第1卷", [22, 65])]),
    ("溪流蛊是什么", [("第1卷", [22])]),
    ("监天塔是什么", [("第4卷", [355, 356, 357, 360])]),
    ("成尊的四个条件", [("第6卷", [119])]),
    ("幽魂魔尊是谁", [("第6卷", [81])]),
    ("春秋蝉有什么能力", [("第1卷", [1, 2])]),
    ("方源怎么得到酒虫", [("第1卷", [17, 16])]),
    ("月霓裳蛊是谁用的", [("第1卷", [70, 71, 72])]),
    ("赤铁舍利蛊是什么", [("第1卷", [98, 99])]),
    ("石窍蛊的作用", [("第1卷", [130, 131, 132])]),
    ("巨阳仙尊是谁", [("第5卷", [300, 400, 500])]),
    ("星宿仙尊是谁", [("第4卷", [200, 300, 355])]),
    ("方源什么时候得到春秋蝉", [("第1卷", [1, 2])]),
    ("古月方正和方源什么关系", [("第1卷", [3, 4, 5, 83])]),
    ("青茅山是什么地方", [("第1卷", [1, 2])]),
    ("白凝冰用的是什么道", [("第2卷", [70, 76, 100])]),
    ("中洲有哪些势力", [("第4卷", [300, 350, 360])]),
    ("北原黄金家族是什么", [("第5卷", [1, 50, 100])]),
    ("方源最后成尊了吗", [("第6卷", [300, 350, 360])]),
    ("爱情蛊在哪里讲", [("第5卷", [208, 209])]),
    ("盗天魔尊是谁", [("第5卷", [400, 500, 700])]),
    ("影宗是什么组织", [("第4卷", [100, 200, 300])]),
    ("月旋蛊怎么来的", [("第1卷", [62, 63, 64])]),
    ("魂道是什么", [("第6卷", [81, 82, 83])]),
    ("方源在擂台上打败了谁", [("第1卷", [83, 84])]),
    ("古月一族在哪", [("第1卷", [1, 2, 3])]),
    ("一转酒虫怎么炼", [("第1卷", [17])]),
]


# 若存在校准测试集（{DATA_DIR}/testset.json）则优先使用
from app.config import DATA_DIR as _DATA_DIR
_ts_path = os.path.join(str(_DATA_DIR), "testset.json")
if os.path.isfile(_ts_path):
    try:
        _ts = json.load(open(_ts_path, encoding="utf-8"))["cases"]
        CASES = [(x["q"], [tuple(g) for g in x["expect"]]) for x in _ts]
        print(f"[testset] 使用校准测试集 {len(CASES)} 题")
    except Exception:
        pass


def load_embedder(data_dir):
    info = json.load(open(os.path.join(data_dir, "info.json"), encoding="utf-8"))
    name = info["model"]
    if "bge-m3" in name.lower():
        from app.config import MODEL_CACHE
        emb = BgeM3Embedder(os.path.join(str(MODEL_CACHE), "bge-m3-onnx"))
        return name, emb, "m3"
    from fastembed import TextEmbedding
    from app.config import MODEL_CACHE
    emb = TextEmbedding(model_name=name, cache_dir=str(MODEL_CACHE))
    return name, emb, "fastembed"


def evaluate(data_dir, name):
    t0 = time.time()
    stores = {}
    for sn in ("novel", "lore"):
        p = os.path.join(data_dir, sn)
        if os.path.isdir(p) and os.path.isfile(os.path.join(p, "vectors.npy")):
            stores[sn] = Store(p)
    if "novel" not in stores:
        return None
    mname, emb, kind = load_embedder(data_dir)
    load_t = time.time() - t0

    results = {}
    for mode in ("rrf", "dense"):
        for k in (3, 5, 8):
            hit = 0
            t_query = []
            for q, expect in CASES:
                tq = time.time()
                if kind == "fastembed":
                    qv = np.asarray(list(emb.embed([q]))[0], dtype=np.float32)
                else:
                    qv = emb.embed(q)
                    if isinstance(qv, np.ndarray) and qv.ndim == 2:
                        qv = qv[0]
                qv = qv / (np.linalg.norm(qv) + 1e-9)
                qt = bigram_tokens(q)
                d = stores["novel"]._dense_ranks(qv, 20)
                b = stores["novel"]._bm25_ranks(qt, 20)
                if mode == "dense":
                    ranked = sorted(d, key=d.get)
                else:
                    sc = {}
                    for i in set(d) | set(b):
                        s = (1.0 / (60 + d[i])) if i in d else 0
                        s += (1.0 / (60 + b[i])) if i in b else 0
                        sc[i] = s
                    ranked = sorted(sc, key=sc.get, reverse=True)
                top = [stores["novel"].meta[i] for i in ranked[:k]]
                ok = any(
                    vol_kw in h.get("vol", "") and h.get("chapter") in chs
                    for vol_kw, chs in expect for h in top
                )
                hit += int(ok)
                t_query.append(time.time() - tq)
            results[f"{mode}@{k}"] = {
                "hit": hit, "total": len(CASES),
                "rate": round(hit / len(CASES), 3),
                "avg_query_s": round(float(np.mean(t_query)), 3),
            }
    return {"model": mname, "load_s": round(load_t, 1), "results": results}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None, help="单个库目录，如 data_m3")
    ap.add_argument("--save", action="store_true", help="写入 eval_results.json（供网页展示）")
    args = ap.parse_args()
    if args.data:
        dirs = [args.data]
    else:
        dirs = [d for d in ("data", "data_m3", "data_jina2") if os.path.isdir(d)]
    saved = {}
    for d in dirs:
        r = evaluate(d, d)
        if r is None:
            print(f"--- {d}: 无 novel 库，跳过")
            continue
        print(f"\n===== {d}  [{r['model']}]  加载耗时 {r['load_s']}s =====")
        for key, v in r["results"].items():
            print(f"  {key:8s} hit={v['hit']}/{v['total']} ({v['rate']:.0%})  平均查询 {v['avg_query_s']}s")
        saved[d] = {
            "model": r["model"], "load_s": r["load_s"],
            "hit3": r["results"]["rrf@3"]["rate"],
            "hit5": r["results"]["rrf@5"]["rate"],
            "hit8": r["results"]["rrf@8"]["rate"],
            "dense5": r["results"]["dense@5"]["rate"],
            "avg_query_s": r["results"]["rrf@5"]["avg_query_s"],
        }
    if args.save and saved:
        out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval_results.json")
        with open(out, "w", encoding="utf-8") as fp:
            json.dump(saved, fp, ensure_ascii=False, indent=2)
        print(f"\nsaved -> {out}")


if __name__ == "__main__":
    main()
