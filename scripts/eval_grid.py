# -*- coding: utf-8 -*-
"""检索参数网格实验：dense_k / bm25_k / RRF常数 / 标题boost / BM25权重
用法：python scripts/eval_grid.py [--model data|data_jina2]
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import DATA_DIR, MODEL_CACHE  # noqa: E402
from app.rag import Store, bigram_tokens  # noqa: E402

GRID = [
    ("base",            dict(dense_k=20, bm25_k=20, rrf_c=60, title_w=0.0, bm25_w=1.0)),
    ("cand50",          dict(dense_k=50, bm25_k=50, rrf_c=60, title_w=0.0, bm25_w=1.0)),
    ("cand50+c30",      dict(dense_k=50, bm25_k=50, rrf_c=30, title_w=0.0, bm25_w=1.0)),
    ("title",           dict(dense_k=50, bm25_k=50, rrf_c=60, title_w=0.015, bm25_w=1.0)),
    ("bm15",            dict(dense_k=50, bm25_k=50, rrf_c=60, title_w=0.0, bm25_w=1.5)),
    ("bm15+title",      dict(dense_k=50, bm25_k=50, rrf_c=60, title_w=0.015, bm25_w=1.5)),
    ("full",            dict(dense_k=50, bm25_k=50, rrf_c=30, title_w=0.015, bm25_w=1.5)),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="data", help="data 或 data_jina2")
    args = ap.parse_args()
    data_dir = os.path.join(os.path.dirname(str(DATA_DIR)), args.model)
    store = Store(os.path.join(data_dir, "novel"))
    info = json.load(open(os.path.join(data_dir, "info.json"), encoding="utf-8"))
    ts = json.load(open(os.path.join(str(DATA_DIR), "testset.json"), encoding="utf-8"))["cases"]

    if "bge-m3" in info["model"].lower():
        from app.embed import BgeM3Embedder
        emb = BgeM3Embedder(os.path.join(str(MODEL_CACHE), "bge-m3-onnx"))
        kind = "m3"
    else:
        from fastembed import TextEmbedding
        emb = TextEmbedding(model_name=info["model"], cache_dir=str(MODEL_CACHE))
        kind = "fe"

    def embed_q(q):
        if kind == "fe":
            v = np.asarray(list(emb.embed([q]))[0], dtype=np.float32)
        else:
            v = emb.embed(q)
            if isinstance(v, np.ndarray) and v.ndim == 2:
                v = v[0]
        return v / (np.linalg.norm(v) + 1e-9)

    vecs = store.vectors
    print(f"model={args.model} [{info['model']}] cases={len(ts)}\n")
    print(f"{'配置':16s} {'rrf@3':>7s} {'rrf@5':>7s} {'rrf@8':>7s} {'dense@5':>8s} {'bm25@5':>7s}")
    for name, p in GRID:
        r3 = r5 = r8 = d5 = b5 = 0
        n = len(ts)
        for c in ts:
            q = c["q"]
            expect = c["expect"]
            qv = embed_q(q)
            qt = bigram_tokens(q)
            sims = vecs @ qv
            dense = {int(i): r + 1 for r, i in enumerate(np.argsort(-sims)[:p["dense_k"]])}
            bm_scores = store.bm25.get_scores(qt)
            bm = {int(i): r + 1 for r, i in enumerate(np.argsort(-bm_scores)[:p["bm25_k"]])}
            sc = {}
            for i in set(dense) | set(bm):
                s = (1.0 / (p["rrf_c"] + dense[i])) if i in dense else 0
                s += p["bm25_w"] * (1.0 / (p["rrf_c"] + bm[i])) if i in bm else 0
                if p["title_w"]:
                    title = store.meta[i].get("title", "")
                    tt = set(bigram_tokens(title))
                    if tt & set(qt):
                        s += p["title_w"]
                sc[i] = s
            ranked = sorted(sc, key=sc.get, reverse=True)
            def hit(k):
                return any(
                    any(vol_kw in store.meta[i].get("vol", "") and store.meta[i].get("chapter") in chs
                        for vol_kw, chs in expect)
                    for i in ranked[:k]
                )
            r3 += int(hit(3)); r5 += int(hit(5)); r8 += int(hit(8))
            d5 += int(any(
                any(vol_kw in store.meta[i].get("vol", "") and store.meta[i].get("chapter") in chs
                    for vol_kw, chs in expect)
                for i in sorted(dense, key=dense.get)[:5]))
            b5 += int(any(
                any(vol_kw in store.meta[i].get("vol", "") and store.meta[i].get("chapter") in chs
                    for vol_kw, chs in expect)
                for i in sorted(bm, key=bm.get)[:5]))
        print(f"{name:16s} {r3/n:>6.0%} {r5/n:>6.0%} {r8/n:>6.0%} {d5/n:>7.0%} {b5/n:>6.0%}")


if __name__ == "__main__":
    main()
