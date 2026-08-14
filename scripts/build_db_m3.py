# -*- coding: utf-8 -*-
"""用 BGE-M3(ONNX) 重建向量库：python scripts/build_db_m3.py [--out data_m3]"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 项目根
from app.embed import BgeM3Embedder  # noqa: E402
from build_db import novel_chapters, lore_chunks  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    proj = os.path.dirname(here)
    parent = os.path.dirname(proj)
    ap.add_argument("--novel-dir", default=os.path.join(parent, "gu-zhen-ren"))
    ap.add_argument("--lore-docx", default=os.path.join(parent, "gu-zhenren-lore", "蛊真人资料合集.docx"))
    ap.add_argument("--out", default=os.path.join(proj, "data_m3"))
    ap.add_argument("--model-dir", default=os.path.join(proj, "model_cache", "bge-m3-onnx"))
    args = ap.parse_args()

    t0 = time.time()
    novel = novel_chapters(args.novel_dir) if os.path.isdir(args.novel_dir) else []
    lore = lore_chunks(args.lore_docx) if os.path.isfile(args.lore_docx) else []
    print(f"novel: {len(novel)}  lore: {len(lore)}")
    if not novel and not lore:
        sys.exit("no data")

    model = BgeM3Embedder(args.model_dir)
    shapes = {}
    for name, docs in (("novel", novel), ("lore", lore)):
        if not docs:
            continue
        out_dir = os.path.join(args.out, name)
        os.makedirs(out_dir, exist_ok=True)
        arr = model.embed([d["text"] for d in docs])
        np_save = __import__("numpy").save(os.path.join(out_dir, "vectors.npy"), arr)
        with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False)
        shapes[name] = list(arr.shape)
        print(f"{name}: {arr.shape}  ({time.time()-t0:.0f}s)")

    info = {
        "model": "BAAI/bge-m3 (onnx)",
        "shapes": shapes,
        "n": sum(v[0] for v in shapes.values()),
        "text_free": False,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(args.out, "info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"done {time.time()-t0:.0f}s -> {args.out}")


if __name__ == "__main__":
    main()
