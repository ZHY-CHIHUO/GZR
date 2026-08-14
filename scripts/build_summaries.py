# -*- coding: utf-8 -*-
"""把 data/summaries.json 的章节摘要向量化，建成 data/novel_sum/ 子库（供检索增强）。
用法：python scripts/build_summaries.py
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import DATA_DIR, MODEL_CACHE  # noqa: E402


def main():
    src = os.path.join(str(DATA_DIR), "summaries.json")
    if not os.path.isfile(src):
        print("没有 data/summaries.json，先运行生成脚本")
        sys.exit(1)
    items = json.load(open(src, encoding="utf-8"))
    print(f"summaries: {len(items)}")

    info = json.load(open(os.path.join(str(DATA_DIR), "info.json"), encoding="utf-8"))
    model = info["model"]
    if "bge-m3" in model.lower():
        from app.embed import BgeM3Embedder
        emb = BgeM3Embedder(os.path.join(str(MODEL_CACHE), "bge-m3-onnx"))
        vecs = emb.embed([it["summary"] for it in items])
        if vecs.ndim == 1:
            vecs = vecs[None, :]
        arr = np.asarray(vecs, dtype=np.float32)
    else:
        from fastembed import TextEmbedding
        emb = TextEmbedding(model_name=model, cache_dir=str(MODEL_CACHE))
        arr = np.vstack([np.asarray(v, dtype=np.float32) for v in emb.embed([it["summary"] for it in items])])
        arr /= np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9

    out_dir = os.path.join(str(DATA_DIR), "novel_sum")
    os.makedirs(out_dir, exist_ok=True)
    np.save(os.path.join(out_dir, "vectors.npy"), arr)
    meta = [{
        "type": "novel", "vol": it["vol"], "chapter": it["chapter"],
        "title": it["title"], "section": "", "text": it["summary"], "via_summary": True,
    } for it in items]
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    print(f"done -> {out_dir}  shape={arr.shape}")


if __name__ == "__main__":
    main()
