# -*- coding: utf-8 -*-
"""把百科词条建成 Jina 向量子库 wiki/（novel/lore 之外的第四个库）。
输出：data_jina2/wiki/vectors.npy + meta.json
用法：python scripts/build_wiki_store.py
说明：当前运行时固定使用 Jina 中文增强索引；不再重建标准 data/wiki，避免重复耗时。
"""
import json
import sys
import time

import numpy as np
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def embed(texts, model_name, cache_dir):
    from fastembed import TextEmbedding
    model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir))
    vecs = []
    B = 32
    for i in range(0, len(texts), B):
        vecs.extend(model.embed(texts[i:i + B]))
    arr = np.vstack([np.asarray(v, dtype=np.float32) for v in vecs])
    arr /= np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9
    return arr


def build_for(dirname):
    d = BASE / dirname
    info = json.load(open(d / "info.json", encoding="utf-8"))
    model = info["model"]
    wiki = json.load(open(BASE / "data_jina2" / "wiki.json", encoding="utf-8"))
    docs = []
    for cat, items in wiki.items():
        if cat == "_deleted":
            continue
        for e in items:
            name = (e.get("name") or "").strip()
            desc = (e.get("desc") or "").strip()
            if not name or not desc:
                continue
            sub = e.get("sub") or ""
            text = name + "：" + desc
            if sub and sub != "其他":
                text += "（" + sub + "）"
            docs.append({"type": "wiki", "name": name, "cat": cat, "sub": sub,
                         "section": e.get("section") or "", "source_path": e.get("source_path") or "",
                         "text": text})
    out = d / "wiki"
    out.mkdir(exist_ok=True)
    arr = embed([x["text"] for x in docs], model, BASE / "model_cache")
    np.save(out / "vectors.npy", arr)
    json.dump(docs, open(out / "meta.json", "w", encoding="utf-8"), ensure_ascii=False)
    print(f"{dirname}: wiki store {len(docs)} 条, dim={arr.shape[1]}")


if __name__ == "__main__":
    t0 = time.time()
    build_for("data_jina2")
    print("done in", round(time.time() - t0, 1), "s")
