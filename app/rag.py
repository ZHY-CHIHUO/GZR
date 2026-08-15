# -*- coding: utf-8 -*-
"""检索与生成核心：本地向量 + BM25 混合检索（RRF 融合）+ DeepSeek 生成。"""
import json
import os
import re

import numpy as np
from rank_bm25 import BM25Okapi


def bigram_tokens(text):
    """字符 unigram + bigram 分词（零依赖，与建库端一致）。"""
    t = re.sub(r"\s+", "", text)
    out = []
    for i in range(len(t)):
        out.append(t[i])
        if i + 1 < len(t):
            out.append(t[i:i + 2])
    return out


class Store:
    """单个子库：vectors.npy + meta.json + 运行时构建 BM25。"""

    def __init__(self, path):
        self.path = path
        self.vectors = np.load(os.path.join(path, "vectors.npy"))
        with open(os.path.join(path, "meta.json"), encoding="utf-8") as f:
            self.meta = json.load(f)
        self.n = len(self.meta)
        self.bm25 = BM25Okapi([bigram_tokens(m["text"]) for m in self.meta])

    def _dense_ranks(self, qv, k):
        scores = self.vectors @ qv
        idx = np.argsort(-scores)[:k]
        return {int(i): r + 1 for r, i in enumerate(idx)}

    def _bm25_ranks(self, qt, k):
        scores = self.bm25.get_scores(qt)
        idx = np.argsort(-scores)[:k]
        return {int(i): r + 1 for r, i in enumerate(idx)}

    def search(self, qv, qt, k, dense_k=20, bm25_k=20):
        d = self._dense_ranks(qv, dense_k)
        b = self._bm25_ranks(qt, bm25_k)
        fused = []
        for i in set(d) | set(b):
            score = 0.0
            if i in d:
                score += 1.0 / (60 + d[i])
            if i in b:
                score += 1.0 / (60 + b[i])
            fused.append((i, score))
        fused.sort(key=lambda x: -x[1])
        out = []
        for i, score in fused[:k]:
            m = dict(self.meta[i])
            m["_rrf"] = score
            out.append(m)
        return out


class Retriever:
    def __init__(self, data_dir, model_cache_dir, top_k=5):
        self.data_dir = str(data_dir)
        self.cache_dir = str(model_cache_dir)
        self.top_k = top_k
        with open(os.path.join(self.data_dir, "info.json"), encoding="utf-8") as f:
            info = json.load(f)
        self.model_name = info["model"]
        self.stores = {}
        for name in ("novel", "lore", "novel_sum", "wiki"):
            p = os.path.join(self.data_dir, name)
            if os.path.isdir(p) and os.path.isfile(os.path.join(p, "vectors.npy")):
                self.stores[name] = Store(p)
        if not self.stores:
            raise RuntimeError(f"data 目录下没有 novel/lore 子库: {self.data_dir}")
        self._embedder = None

    def _embed(self, text):
        if self._embedder is None:
            if "bge-m3" in self.model_name.lower():
                from .embed import BgeM3Embedder
                self._embedder = BgeM3Embedder(os.path.join(self.cache_dir, "bge-m3-onnx"))
                self._m3 = True
            else:
                from fastembed import TextEmbedding
                self._embedder = TextEmbedding(model_name=self.model_name, cache_dir=self.cache_dir)
                self._m3 = False
        if getattr(self, "_m3", False):
            return self._embedder.embed(text)
        v = np.asarray(list(self._embedder.embed([text]))[0], dtype=np.float32)
        return v / (np.linalg.norm(v) + 1e-9)

    def search(self, query, k=None, scope="all"):
        """scope: all=正文+设定+百科, novel=仅正文(+摘要), lore=仅设定+百科"""
        k = k or self.top_k
        qv = self._embed(query)
        qt = bigram_tokens(query)
        hits = []
        if scope in ("all", "novel") and "novel" in self.stores:
            # 正文为主；摘要库小、库内排名不可跨库比较，仅作补位且需过相似度门槛
            n_need = max(1, k - 2) if scope == "all" else k
            merged = list(self.stores["novel"].search(qv, qt, n_need))
            if "novel_sum" in self.stores:
                seen = {(h.get("vol"), h.get("chapter")) for h in merged}
                sum_sim = self.stores["novel_sum"].vectors @ qv
                if float(np.max(sum_sim)) >= 0.42:  # 绝对相似度门槛，防不相关摘要占位
                    for h in self.stores["novel_sum"].search(qv, qt, k):
                        key = (h.get("vol"), h.get("chapter"))
                        if key in seen:
                            continue
                        seen.add(key)
                        h["via_summary"] = True
                        merged.append(h)
                        break  # 只补一个摘要位
            hits.extend(merged[:n_need])
        if scope in ("all", "lore") and "lore" in self.stores:
            lore_hits = self.stores["lore"].search(qv, qt, k)
            if lore_hits:
                hits = hits[: max(0, k - 1)] + [lore_hits[0]]
        if scope in ("all", "lore") and "wiki" in self.stores:
            # 百科词条：相似度门槛，取最高 1 条（可与检索到的正文/设定互补）
            wsim = self.stores["wiki"].vectors @ qv
            wi = int(np.argmax(wsim))
            if float(wsim[wi]) >= 0.40:
                w = dict(self.stores["wiki"].meta[wi])
                w["_sim"] = float(wsim[wi])
                if not any(h.get("name") == w.get("name") and h.get("cat") == w.get("cat") for h in hits):
                    hits = hits[: max(0, k - 1)] + [w]
        for h in hits:
            h.setdefault("store", "novel")
        return hits[:k]


def format_source(h):
    excerpt = (h.get("text") or "")[:200]
    if h.get("type") == "wiki":
        return {
            "type": "wiki",
            "label": f"百科词条《{h.get('name')}》",
            "name": h.get("name"), "cat": h.get("cat"),
            "title": h.get("name"), "excerpt": excerpt,
        }
    if h.get("type") == "lore":
        return {
            "type": "lore",
            "label": f"设定集《{h.get('section') or h.get('title')}》",
            "chapter": h.get("chapter"), "vol": h.get("vol"),
            "title": h.get("title"), "excerpt": excerpt,
        }
    tag = "（摘要命中）" if h.get("via_summary") else ""
    return {
        "type": "novel",
        "label": f"{h.get('vol')}·第{h.get('chapter')}章·{h.get('title')}{tag}",
        "chapter": h.get("chapter"), "vol": h.get("vol"),
        "title": h.get("title"), "excerpt": excerpt,
        "via_summary": bool(h.get("via_summary")),
    }


def build_prompt(question, hits, excerpt_chars=600):
    refs = []
    for i, h in enumerate(hits, 1):
        if h.get("type") == "wiki":
            label = f"百科词条《{h.get('name')}》"
        elif h.get("type") == "lore":
            label = f"设定集《{h.get('section') or h.get('title')}》"
        else:
            label = f"正文《{h.get('vol')}·第{h.get('chapter')}章·{h.get('title')}》"
        excerpt = (h.get("text") or "")[:excerpt_chars]
        refs.append(f"[{i}] {label}\n{excerpt}")
    system = (
        "你是《蛊真人》的资深书迷助手，只依据【参考资料】回答，使用简体中文。"
        "每条参考资料开头都标注了「第N卷·第N章·标题」或设定集小节名，请充分利用这些标题："
        "标题含「（上）（下）」的，上篇即该内容首次出现。"
        "当用户问某内容的首次/第一次出现、在哪一章时，直接回答检索到的最早相关章节（卷+章号+标题），"
        "即便不能百分百确定是全书首次，也要给出「检索到的最早章节是第X章」这类答案，不要只说「未查到」。"
        "确实完全无关时才说未查到，并说明检索到了什么。不要编造原文没有的细节。"
        "若【参考资料】确实没有相关内容：请明确写出『资料库未检索到相关内容，以下为基于通用知识的回答，请自行核对』，"
        "并顺带给出一两个可能包含该信息的章节/词条方向供用户查证，不要硬编造细节。"
    )
    user = "【参考资料】\n" + "\n\n".join(refs) + f"\n\n【问题】{question}\n\n回答末尾用一行列出依据来源编号。"
    return system, user


def mock_answer(hits):
    lines = ["（测试模式：未配置 DEEPSEEK_API_KEY，仅展示检索结果）", "检索到以下相关来源："]
    for i, h in enumerate(hits, 1):
        if h.get("type") == "wiki":
            lines.append(f"{i}. 百科词条《{h.get('name')}》")
        elif h.get("type") == "lore":
            lines.append(f"{i}. 设定集《{h.get('section') or h.get('title')}》")
        else:
            lines.append(f"{i}. {h.get('vol')}·第{h.get('chapter')}章·{h.get('title')}")
    return "\n".join(lines)


def ask_llm(system, user, api_key, base_url, model, history=None):
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    messages = [{"role": "system", "content": system}]
    for h in (history or [])[-8:]:
        role = h.get("role")
        content = str(h.get("content") or "")[:2000]
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user})
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.4,
        max_tokens=1024,
    )
    return resp.choices[0].message.content or ""


def estimate_cost(system, user, answer, in_price=3.0, out_price=6.0):
    """粗略估算（中文约 0.7 token/字），单位：元。"""
    tin = int((len(system) + len(user)) * 0.7)
    tout = int(len(answer) * 0.7)
    return round((tin * in_price + tout * out_price) / 1e6, 4)
