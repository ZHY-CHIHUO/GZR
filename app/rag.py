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
            m["_idx"] = i
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
            for h in merged:
                h["_store"] = "novel"
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
                        h["_store"] = "novel_sum"
                        merged.append(h)
                        break  # 只补一个摘要位
            hits.extend(merged[:n_need])
        if scope in ("all", "lore") and "lore" in self.stores:
            lore_hits = self.stores["lore"].search(qv, qt, k)
            if lore_hits:
                lore_hits[0]["_store"] = "lore"
                hits = hits[: max(0, k - 1)] + [lore_hits[0]]
        if scope in ("all", "lore") and "wiki" in self.stores:
            # 百科词条：相似度门槛，取最高 1 条（可与检索到的正文/设定互补）
            wsim = self.stores["wiki"].vectors @ qv
            wi = int(np.argmax(wsim))
            if float(wsim[wi]) >= 0.40:
                w = dict(self.stores["wiki"].meta[wi])
                w["_sim"] = float(wsim[wi])
                w["_idx"] = wi
                w["_store"] = "wiki"
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


def build_prompt(question, hits, excerpt_chars=1200):
    refs = []
    # 提取问题中的关键短语（如诗句、成语、专名），优先居中截取包含关键词的段落
    import re
    keywords = [w for w in re.split(r'[,，.。?？!！\s"“”]+', question) if len(w) >= 2]

    for i, h in enumerate(hits, 1):
        if h.get("type") == "wiki":
            label = f"百科词条《{h.get('name')}》"
        elif h.get("type") == "lore":
            label = f"设定集《{h.get('section') or h.get('title')}》"
        else:
            label = f"正文《{h.get('vol')}·第{h.get('chapter')}章·{h.get('title')}》"
        full_text = h.get("text") or ""
        if len(full_text) <= excerpt_chars:
            excerpt = full_text
        else:
            # 尝试定位关键词在整章中的位置，把最相关的上下文切给大模型
            best_pos = -1
            for kw in sorted(keywords, key=len, reverse=True):
                pos = full_text.find(kw)
                if pos != -1:
                    best_pos = pos
                    break
            if best_pos != -1:
                start = max(0, best_pos - 300)
                end = min(len(full_text), start + excerpt_chars)
                if end - start < excerpt_chars:
                    start = max(0, end - excerpt_chars)
                prefix = "..." if start > 0 else ""
                suffix = "..." if end < len(full_text) else ""
                excerpt = prefix + full_text[start:end] + suffix
            else:
                excerpt = full_text[:excerpt_chars] + "..."
        refs.append(f"[{i}] {label}\n{excerpt}")
    system = (
        "你是《蛊真人》的资深书迷助手，只依据【参考资料】回答，使用简体中文。"
        "每条参考资料开头都标注了「第N卷·第N章·标题」或设定集小节名，请充分利用这些标题："
        "标题含「（上）（下）」的，上篇即该内容首次出现。"
        "当用户问某内容的首次/第一次出现、在哪一章时，直接回答检索到的最早相关章节（卷+章号+标题），"
        "即便不能百分百确定是全书首次，也要给出「检索到的最早章节是第X章」这类答案，不要只说「未查到」。"
        "确实完全无关时才说未查到，并说明检索到了什么。不要编造原文没有的细节。"
        "若【参考资料】确实没有相关内容：请明确写出『资料库未检索到相关内容，以下为基于通用知识的回答，请自行核对』，"
        "并顺带给出一两个可能包含该信息的章节/词条方向供用户查证，不要硬编造细节；"
        "通用知识回答时不要再写『依据来源』行（没有可引用的资料条目）。"
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
        max_tokens=4096,
    )
    return resp.choices[0].message.content or ""


def estimate_cost(system, user, answer, in_price=3.0, out_price=6.0):
    """粗略估算（中文约 0.7 token/字），单位：元。"""
    tin = int((len(system) + len(user)) * 0.7)
    tout = int(len(answer) * 0.7)
    return round((tin * in_price + tout * out_price) / 1e6, 4)

def _chat_web(system, user, api_key, base_url, model, history=None):
    """兼容路径：chat.completions + web_search 工具（部分服务商/代理支持联网）。"""
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    messages = [{"role": "system", "content": system}]
    for h in (history or [])[-8:]:
        role = h.get("role")
        c = str(h.get("content") or "")[:2000]
        if role in ("user", "assistant") and c:
            messages.append({"role": role, "content": c})
    messages.append({"role": "user", "content": user})
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=[{"type": "web_search"}],
        tool_choice="auto",
        temperature=0.4,
  max_tokens=4096,
    )
    msg = resp.choices[0].message
    text = (msg.content or "").strip()
    citations = []
    for c in (getattr(msg, "citations", None) or []):
        if isinstance(c, dict):
            citations.append({"url": c.get("url", ""), "title": c.get("title", "") or c.get("url", "")})
        elif isinstance(c, str):
            citations.append({"url": c, "title": c})
    searched = bool(getattr(msg, "tool_calls", None)) or bool(citations)
    return text, citations, searched


def ask_llm_web(system, user, api_key, base_url, model, history=None):
    """联网回答：优先 DeepSeek 官方 Responses API + 原生 web_search，
    失败则回退到 chat.completions + web_search 工具（兼容代理/新-api）。

    返回 (answer_text, citations, searched)。"""
    err_msgs = []
    # 1) 官方 Responses API 路径
    try:
        import json as _json
        import urllib.request as _url
        import urllib.error as _urlerr

        web_model = model if str(model).startswith("deepseek-v4") else "deepseek-v4-flash"
        input_items = []
        for h in (history or [])[-8:]:
            role = h.get("role")
            content = str(h.get("content") or "")[:2000]
            if role in ("user", "assistant") and content:
                input_items.append({"role": role, "content": content})
        input_items.append({"role": "user", "content": user})
        payload = {
            "model": web_model,
            "instructions": system,
            "input": input_items,
            "tools": [{"type": "web_search"}],
            "reasoning": {"effort": "none"},
            "max_output_tokens": 1100,
        }
        endpoint = (str(base_url).rstrip("/")) + "/responses"
        req = _url.Request(
            endpoint,
            data=_json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
            method="POST",
        )
        try:
            resp = _url.urlopen(req, timeout=90)
            data = _json.loads(resp.read().decode("utf-8"))
        except _urlerr.HTTPError as e:
            raise RuntimeError(f"Responses HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:160]}")
        except Exception as e:
            raise RuntimeError(f"Responses 连接失败：{e}")
        texts, citations, searched = [], [], False
        for item in data.get("output", []) or []:
            if item.get("type") == "web_search_call":
                searched = True
            if item.get("type") == "message":
                for part in item.get("content", []) or []:
                    if part.get("type") == "output_text":
                        t = part.get("text") or ""
                        if t:
                            texts.append(t)
                        for ann in (part.get("annotations") or []):
                            if ann.get("type") == "url_citation":
                                citations.append({
                                    "url": ann.get("url") or "",
                                    "title": ann.get("title") or ann.get("url") or "",
                                })
        text = (chr(10).join(texts)).strip()
        if text:
            return text, citations, searched
        raise RuntimeError("Responses 返回空文本")
    except Exception as e:
        err_msgs.append(str(e))

    # 2) 兼容路径
    try:
        text, citations, searched = _chat_web(system, user, api_key, base_url, model, history)
        if text:
            return text, citations, searched
        raise RuntimeError("chat 联网返回空文本")
    except Exception as e:
        err_msgs.append(str(e))

    raise RuntimeError("；".join(err_msgs) or "未知联网失败")


