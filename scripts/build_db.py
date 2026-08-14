# -*- coding: utf-8 -*-
"""《蛊真人》RAG 建库脚本
输入：
  - gu-zhen-ren/   2334 章正文 txt（按卷分章）
  - 蛊真人资料合集.docx   设定资料（约 40 万字）
输出（data/）：
  - novel/vectors.npy + novel/meta.json   正文子库（一章一条）
  - lore/vectors.npy + lore/meta.json     设定子库（按小节切块）
  - info.json                             模型名/维度/数量
用法：
  python scripts/build_db.py
  python scripts/build_db.py --model BAAI/bge-small-zh-v1.5
"""
import argparse
import json
import os
import re
import sys
import time

import numpy as np


def novel_chapters(root):
    """扫描小说目录，一章一条。"""
    docs = []
    for vol in sorted(os.listdir(root)):
        vdir = os.path.join(root, vol)
        if not os.path.isdir(vdir):
            continue
        for fn in sorted(os.listdir(vdir)):
            if not fn.endswith(".txt"):
                continue
            path = os.path.join(vdir, fn)
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
            if not lines:
                continue
            title = lines[0]
            body = "\n".join(lines[1:])
            m = re.search(r"第(\d+)章", fn)
            chapter = int(m.group(1)) if m else 0
            docs.append({
                "type": "novel", "vol": vol, "chapter": chapter,
                "title": title, "section": "", "text": body,
            })
    return docs


def lore_chunks(docx_path, chunk_chars=700, overlap=100):
    """解析设定 docx：按小节标题切分，超长小节再按窗口切块。"""
    from docx import Document
    doc = Document(docx_path)
    paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    paras = [p for p in paras if not re.fullmatch(r"\[\d+\]\s*", p)]  # 去脚注残留

    def is_heading(p):
        return (len(p) <= 24 and "：" not in p
                and not p.endswith(("。", "！", "？", "；", "，", "、")))

    chunks = []
    section = "未分类"
    buf = ""
    for p in paras:
        if is_heading(p):
            if buf:
                chunks.append((section, buf))
            section = p
            buf = p + "\n"
            continue
        if buf and len(buf) + len(p) > chunk_chars:
            chunks.append((section, buf))
            buf = buf[-overlap:] + "\n" + p + "\n"
        else:
            buf += p + "\n"
    if buf:
        chunks.append((section, buf))
    return [{
        "type": "lore", "vol": "", "chapter": 0,
        "title": sec, "section": sec, "text": text.strip(),
    } for sec, text in chunks]


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


def build_and_save(name, docs, out_dir, model_name, cache_dir):
    os.makedirs(os.path.join(out_dir, name), exist_ok=True)
    arr = embed([d["text"] for d in docs], model_name, cache_dir)
    np.save(os.path.join(out_dir, name, "vectors.npy"), arr)
    with open(os.path.join(out_dir, name, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False)
    return arr.shape


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    proj = os.path.dirname(here)
    parent = os.path.dirname(proj)
    ap.add_argument("--novel-dir", default=os.path.join(parent, "gu-zhen-ren"))
    ap.add_argument("--lore-docx", default=os.path.join(parent, "gu-zhenren-lore", "蛊真人资料合集.docx"))
    ap.add_argument("--out", default=os.path.join(proj, "data"))
    ap.add_argument("--cache-dir", default=os.path.join(proj, "model_cache"))
    ap.add_argument("--model", default="BAAI/bge-m3")
    ap.add_argument("--text-free", action="store_true", help="不保存原文（仅向量+元数据）")
    args = ap.parse_args()

    t0 = time.time()
    novel = novel_chapters(args.novel_dir) if os.path.isdir(args.novel_dir) else []
    print(f"novel: {len(novel)} chapters")
    lore = lore_chunks(args.lore_docx) if os.path.isfile(args.lore_docx) else []
    print(f"lore: {len(lore)} chunks")
    if not novel and not lore:
        print("没有可建库的数据，退出")
        sys.exit(1)

    model_name = args.model
    shapes = {}
    for name, docs in (("novel", novel), ("lore", lore)):
        if not docs:
            continue
        try:
            shapes[name] = build_and_save(name, docs, args.out, model_name, args.cache_dir)
        except Exception as e:
            print(f"[warn] {model_name} 失败: {e}")
            if model_name != "BAAI/bge-small-zh-v1.5":
                model_name = "BAAI/bge-small-zh-v1.5"
                print(f"[info] 回退到 {model_name}，重新建库")
                shapes = {}
                for n2, d2 in (("novel", novel), ("lore", lore)):
                    if d2:
                        shapes[n2] = build_and_save(n2, d2, args.out, model_name, args.cache_dir)
                break
            raise

    info = {
        "model": model_name,
        "shapes": {k: list(v) for k, v in shapes.items()},
        "n": sum(v[0] for v in shapes.values()),
        "text_free": bool(args.text_free),
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(args.out, "info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"done in {time.time() - t0:.0f}s -> {args.out}")
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
