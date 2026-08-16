# -*- coding: utf-8 -*-
"""《蛊真人》RAG 本地网页服务。
启动：uvicorn app.main:app --port 8000
"""
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, library
from .rag import Retriever, ask_llm, build_prompt, estimate_cost, format_source, mock_answer

APP_VERSION = "1.0.0"

retriever: Retriever | None = None


def reload_retriever():
    global retriever
    retriever = Retriever(config.DATA_DIR, config.MODEL_CACHE, top_k=config.TOP_K)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    reload_retriever()
    yield


app = FastAPI(title="蛊真人 RAG", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def no_cache_static(request, call_next):
    """静态资源不缓存：前端改动后浏览器刷新即可生效。"""
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, max-age=0"
    return response


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


class AskReq(BaseModel):
    question: str
    scope: str = "all"          # all / novel / lore
    history: list = []          # [{role, content}, ...]
    web_fallback: bool = True   # 检索不到时是否联网搜索（网络回答）
    first_occurrence: bool = False  # 强制按原著全文顺序定位首次命中
    original_regex: bool = False    # first_occurrence 时将问题按正则表达式解释


class SettingsReq(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    embed_model: str | None = None   # small / m3 / jina


class TestReq(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class NovelSearchReq(BaseModel):
    query: str
    is_regex: bool = False
    vol: str | None = None
    limit: int = 60


class LoreSearchReq(BaseModel):
    query: str
    is_regex: bool = False
    limit: int = 80


def _novel_text_search(query: str, is_regex: bool = False, vol: str | None = None,
                       limit: int = 60, stop_after_first: bool = False):
    """按卷、章自然顺序扫描原著；既供阅读器搜索，也供问答作可核验的精确证据。"""
    q = (query or "").strip()
    if not q:
        return {"results": [], "total_matches": 0, "chapters_matched": 0, "query": q, "is_regex": is_regex}
    try:
        pattern = re.compile(q if is_regex else re.escape(q), re.IGNORECASE)
    except re.error as e:
        raise ValueError(f"正则表达式语法错误：{e}") from e
    if is_regex and pattern.search(""):
        raise ValueError("正则表达式不能匹配空文本，请至少匹配一个字符")

    root = library.NOVEL_ROOT.resolve()
    if not root.is_dir():
        return {"results": [], "total_matches": 0, "chapters_matched": 0, "query": q, "is_regex": is_regex}

    results, total_matches, truncated = [], 0, False
    limit = max(1, min(int(limit or 60), 200))
    for vdir in sorted(os.listdir(root), key=library._natural_key):
        if vol and vdir != vol:
            continue
        vp = root / vdir
        if not vp.is_dir():
            continue
        for fn in sorted(os.listdir(vp), key=library._natural_key):
            if not fn.endswith(".txt"):
                continue
            fp = vp / fn
            try:
                content = fp.read_text(encoding="utf-8")
            except OSError:
                continue
            found = list(pattern.finditer(content))
            if not found:
                continue
            ch_match = re.match(r"第(\d+)章\.txt", fn)
            chapter = int(ch_match.group(1)) if ch_match else 0
            lines = content.splitlines()
            snippets = []
            for match in found[:3]:
                start, end = max(0, match.start() - 44), min(len(content), match.end() + 72)
                snippets.append({
                    "line": content.count("\n", 0, match.start()) + 1,
                    "snippet": " ".join(content[start:end].split()),
                    "match": match.group(0),
                })
            results.append({
                "vol": vdir, "chapter": chapter,
                "title": library._first_title(lines) if lines else fn,
                "count": len(found), "snippets": snippets,
            })
            total_matches += len(found)
            if stop_after_first:
                return {"results": results, "total_matches": total_matches, "chapters_matched": 1,
                        "query": q, "is_regex": is_regex, "truncated": False}
            if len(results) >= limit:
                truncated = True
                break
        if truncated:
            break
    return {"results": results, "total_matches": total_matches, "chapters_matched": len(results),
            "query": q, "is_regex": is_regex, "truncated": truncated}


@app.post("/api/novel/search")
def search_novel_text(req: NovelSearchReq):
    """原著全文检索：支持文字、跨行片段和正则表达式。"""
    try:
        return _novel_text_search(req.query, req.is_regex, req.vol, req.limit)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


class LocateReq(BaseModel):
    vol: str
    chapter: int


# ---------- 页面 ----------

@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/files/{path:path}")
def serve_file(path: str):
    """服务插图版 PDF（浏览器原生渲染）。"""
    root = library.PDF_ROOT.resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(404, "文件不存在")
    # 显式 inline：让浏览器内嵌渲染而不是下载；no-store 防止缓存旧响应
    import urllib.parse as _up
    safe = _up.quote(target.name)
    return FileResponse(
        target,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{safe}",
            "Cache-Control": "no-store",
        },
    )


# ---------- 问答 ----------

@app.get("/api/health")
def health():
    if retriever is None:
        return {"ok": False, "error": "not loaded"}
    return {
        "ok": True,
        "has_key": bool(config.KEY),
        "key_set_in_ui": bool(config.KEY),
        "base_url": config.BASE_URL,
        "model": config.MODEL,
        "embed_model": retriever.model_name,
        "stores": {name: s.n for name, s in retriever.stores.items()},
        "top_k": config.TOP_K,
        "data_dir": config.DATA_DIR.name,
    }


_RETRY_MARKS = ("未查到", "未找到", "没有找到", "没有检索到", "未检索到", "资料中未提及", "资料中未记载", "未能查到", "无法确认", "没有收录")


def _force_wiki_hits(q, hits, limit=3):
    """问题中出现的百科词条名，强制加入参考资料（不依赖向量相似度）。"""
    try:
        cites = _wiki_cites_in(q, limit=limit)
    except Exception:
        cites = []
    if not cites:
        return hits
    out = list(hits)
    for c in cites:
        entry = None
        for e in (_wiki.get(c.get("cat")) or []):
            if e.get("name") == c.get("name"):
                entry = e
                break
        if entry is None:
            for _cat, items in (_wiki or {}).items():
                for e in items:
                    if e.get("name") == c.get("name"):
                        entry = e
                        break
                if entry:
                    break
        if entry is None:
            continue
        hit = {
            "type": "wiki", "name": c.get("name"), "cat": c.get("cat"),
            "section": entry.get("section", ""), "sub": entry.get("sub", ""),
            "text": entry.get("desc", ""),
        }
        if not any(h.get("type") == "wiki" and h.get("name") == c.get("name") for h in out):
            out.append(hit)
    return out


def _exact_wiki_hits(q, limit=3):
    """字面命中百科正文时强制召回，避免短诗句被向量相似度阈值过滤。"""
    query = (q or "").strip()
    if len(query) < 2:
        return []
    try:
        _load_content()
    except Exception:
        return []
    out = []
    for cat, entries in (_wiki or {}).items():
        if cat == "_deleted":
            continue
        for entry in entries:
            text = str(entry.get("desc") or "")
            pos = text.find(query)
            if pos < 0:
                continue
            start, end = max(0, pos - 72), min(len(text), pos + len(query) + 144)
            excerpt = " ".join(text[start:end].split())
            out.append({
                "type": "wiki", "name": entry.get("name", ""), "cat": cat,
                "section": entry.get("section", ""), "sub": entry.get("sub", ""),
                "text": text, "_exact_excerpt": excerpt,
            })
            if len(out) >= limit:
                return out
    return out


def _collection_poetry_response(query: str):
    """精确命中书友二创诗词时直接给出来源与性质，防止误报“资料库没有”。"""
    matches = [h for h in _exact_wiki_hits(query) if "书友二创" in (h.get("text") or "")]
    if not matches:
        return None
    hit = matches[0]
    text = hit["text"]
    poem = ""
    m = re.search(r"【诗词内容】\s*(.*?)(?:\s*【背景说明】|$)", text, re.S)
    if m:
        poem = m.group(1).strip()
    label = hit.get("sub") or hit.get("name") or "相关赞诗"
    quoted_poem = "> " + poem.replace("\n", "\n> ") + "\n\n" if poem else ""
    answer = (f"“{query}”**不是《蛊真人》原著正文**。\n\n"
              f"它收录在《蛊真人》资料合集的「第十三章十尊者诗」，属于**书友二创 / 尊者赞诗**："
              f"**{label}**。\n\n"
              + quoted_poem
              + "因此可作为资料合集与百科收录内容查阅，但不能标注或回答为原著原文。")
    source = format_source(dict(hit, text=hit.get("_exact_excerpt") or text))
    source["label"] = f"百科词条《{hit.get('name')}》（书友二创，非原著）"
    return {"answer": answer, "sources": [source], "wiki_cites": [{"name": hit.get("name"), "cat": hit.get("cat")}]}


def _retry_extra(q, hits, scope):
    """补救检索：用问题中出现的词条名在正文/设定里再找相关片段。"""
    try:
        cites = _wiki_cites_in(q, limit=5)
    except Exception:
        cites = []
    extra = []
    for c in cites[:3]:
        try:
            for h in retriever.search(c.get("name", ""), k=3, scope=scope):
                if h.get("type") == "wiki":
                    continue
                if any(x.get("title") == h.get("title") and x.get("vol") == h.get("vol") for x in hits + extra):
                    continue
                extra.append(h)
        except Exception:
            continue
    return extra


def _web_back_to_rag(web_answer, q, scope):
    """网络回答要点反哺资料库检索：用回答内容作查询再搜一次，
    返回过相似度门槛的命中（供整合回答引用具体章节）。"""
    try:
        query = (q + " " + (web_answer or "")[:300]).strip() or q
        hits = _force_wiki_hits(query, retriever.search(query, k=4, scope=scope))
        qv = retriever._embed(query)
        good = []
        for h in hits:
            st = retriever.stores.get(h.get("_store") or "novel")
            idx = h.get("_idx")
            if st is None or idx is None:
                continue
            sim = float(st.vectors[idx] @ qv)
            if sim >= 0.42:
                good.append(h)
        return good[:3]
    except Exception:
        return []


def _supplement_irrelevant(merged):
    """补充检索的内容与问题无关（非《蛊真人》内容）时返回 True：
    不展示资料库依据卡片，整体回退为纯网络回答。"""
    if any(m in merged for m in ("资料库未收录相关内容", "资料库未检索到", "基于通用知识的回答", "没有检索到")):
        return True
    return not bool(re.search(r"\[\d{1,2}\]", merged))

def _first_occurrence_query(question: str):
    """识别“某段文字/人物在原文第一次出现于第几章”这类可由全文扫描确定的问题。"""
    q = (question or "").strip()
    has_first = bool(re.search(r"(?:第一次|首次|最早).{0,14}(?:出现|提及|提到)|(?:出现|提及|提到).{0,14}(?:第一次|首次|最早)", q))
    has_location = bool(re.search(r"(?:第几章|哪一章|第.?章|在哪里|何处)", q))
    if not (has_first and has_location):
        return None
    # 优先采用引号中的原文片段，避免把整句提问误当作检索词。
    quoted = re.search(r"[“\"「]([^”\"」]{2,120})[”\"」]", q)
    if quoted:
        return quoted.group(1).strip()
    # 无引号时兼容“方源第一次出现在哪一章”这类实体定位问题。
    candidate = re.sub(r"^(?:请问|请|帮我|帮忙|查一下|查下|搜索一下|搜索)", "", q)
    candidate = re.sub(r"(?:在)?原文(?:中|里)?(?:最早|第一次|首次).*$", "", candidate)
    candidate = re.sub(r"(?:最早|第一次|首次).*$", "", candidate)
    candidate = re.sub(r"(?:在)?原文(?:中|里)?(?:出现|提及|提到).*$", "", candidate)
    candidate = re.sub(r"(?:出现|提及|提到).*$", "", candidate)
    candidate = candidate.strip(" ：:，,。？?！! ")
    return candidate if 1 < len(candidate) <= 60 else None


def _first_occurrence_response(query: str, is_regex: bool = False):
    """返回可复核的全文首章命中；不让向量排序或模型猜测影响“第一次”。"""
    try:
        found = _novel_text_search(query, is_regex=is_regex, limit=1, stop_after_first=True)
    except ValueError as e:
        return {"answer": f"原文正则表达式有误：{e}", "sources": [],
                "exact_lookup": {"query": query, "found": False, "error": str(e)}}
    if not found["results"]:
        collection = _collection_poetry_response(query)
        if collection:
            collection["answer"] = (f"我已按卷、章顺序对《蛊真人》原著正文做精确全文检索，未找到“{query}”。\n\n"
                                    + collection["answer"])
            collection["exact_lookup"] = {"query": query, "found": False, "original_found": False}
            return collection
        return {
            "answer": f"我已按卷、章顺序对原著正文做精确全文检索，未找到“{query}”。\n\n"
                      "这表示当前本地原文库中没有该连续文本；可尝试缩短片段、检查异体字或改用阅读页的正则搜索。",
            "sources": [],
            "exact_lookup": {"query": query, "found": False},
        }
    item = found["results"][0]
    snip = item["snippets"][0] if item.get("snippets") else {}
    line = snip.get("line")
    line_note = f"（原始文本第 {line} 行）" if line else ""
    answer = (f"“{query}”在本地《蛊真人》原著正文中**第一次出现**于：\n\n"
              f"**{item['vol']} · 第 {item['chapter']} 章 · {item['title']}** {line_note}\n\n"
              f"> {snip.get('snippet', '')}\n\n"
              "此结果由原著全文按卷、章顺序精确扫描得出，不依赖 RAG 相似度排序。")
    source = {
        "type": "novel", "label": f"{item['vol']}·第{item['chapter']}章·{item['title']}（全文首次命中）",
        "chapter": item["chapter"], "vol": item["vol"], "title": item["title"],
        "excerpt": snip.get("snippet", ""),
    }
    return {"answer": answer, "sources": [source],
            "exact_lookup": {"query": query, "found": True, "vol": item["vol"], "chapter": item["chapter"], "line": line}}



@app.post("/api/ask")
def ask(req: AskReq):
    q = (req.question or "").strip()
    if not q:
        return JSONResponse({"error": "问题不能为空"}, status_code=400)
    if retriever is None:
        return JSONResponse({"error": "检索库未加载"}, status_code=503)
    # 可被精确全文扫描判定的“首次出现”问题优先走确定性路径：RAG 只负责语义问答，不能证明全书首次。
    first_query = q if req.first_occurrence else _first_occurrence_query(q)
    if first_query:
        located = _first_occurrence_response(first_query, is_regex=req.original_regex)
        if located is not None:
            return {
                **located,
                "cost_rmb": 0.0,
                "mock": False,
                "web": False,
                "wiki_cites": _wiki_cites_in(q),
            }
    # 多轮追问时，结合上一轮用户提问增强短句/代词检索（如上一问是诗句，下一问“这句呢”或“在哪一章”）
    search_q = q
    if req.history and len(q) <= 15:
        last_user = next((h.get("content", "") for h in reversed(req.history) if h.get("role") == "user"), "")
        if last_user and last_user != q:
            search_q = (last_user[:30] + " " + q).strip()

    # 对资料合集中的二创诗词做字面证据路由：短句必须先说明“收录但非原著”，不能被向量阈值漏掉后联网猜测。
    collection = _collection_poetry_response(q)
    if collection:
        return {**collection, "cost_rmb": 0.0, "mock": False, "web": False}
    # 一次检索（普通 + 追问增强 + 词条名强制召回 + 词条名原文补充）
    hits = _force_wiki_hits(q, retriever.search(search_q, scope=req.scope))
    exact_wiki = _exact_wiki_hits(q)
    for hit in exact_wiki:
        if not any(h.get("type") == "wiki" and h.get("name") == hit.get("name") and h.get("sub") == hit.get("sub") for h in hits):
            hits.insert(0, hit)
    hits = hits + _retry_extra(q, hits, req.scope)
    system, user = build_prompt(q, hits, config.EXCERPT_CHARS)
    # 联网能力并入首次调用：资料库能答就答，答不了让模型直接联网（省一次调用）
    system_w = system + (
        "你有联网搜索工具 web_search：当【参考资料】确实没有相关内容、无法回答时，"
        "请调用 web_search 联网搜索获取信息后回答；若资料库能回答，则不要联网。"
        "联网回答时，回答末尾单独一行给出参考来源，格式：依据来源：[1] 网站名 网址；[2] 网站名 网址……"
    )
    web_sources = []
    web_used = False
    combined = False
    extra_sources = []
    if config.KEY:
        try:
            if req.web_fallback:
                from .rag import _chat_web
                answer, cites, searched = _chat_web(
                    system_w, user, config.KEY, config.BASE_URL, config.MODEL, history=req.history
                )
            else:
                answer = ask_llm(system, user, config.KEY, config.BASE_URL, config.MODEL, history=req.history)
                cites, searched = [], False
        except Exception:
            # 联网工具不可用等异常：退回普通资料库回答
            try:
                answer = ask_llm(system, user, config.KEY, config.BASE_URL, config.MODEL, history=req.history)
                cites, searched = [], False
            except Exception as e:
                return JSONResponse({"error": f"AI 调用失败：{e}"}, status_code=502)
        # 兜底：模型没联网却仍说"未查到" → 强制联网回答
        if not searched and req.web_fallback and any(m in answer for m in _RETRY_MARKS):
            try:
                from .rag import ask_llm_web
                web_system = ("你是《蛊真人》资料问答助手，当前资料库未能提供答案，请使用联网搜索获取信息，"
                              "并**按平时回答的同样格式**组织内容："
                              "用简体中文，要点用 **加粗** 标注；回答简洁、分点清晰；"
                              "回答末尾单独一行给出参考来源，格式：依据来源：[1] 网站名 网址；[2] 网站名 网址……（网址尽量完整），"
                              "多个来源用分号分隔；确实查不到就明确说明无法确认。")
                wa, wc, ws = ask_llm_web(web_system, q, config.KEY, config.BASE_URL, config.MODEL, history=req.history)
                if wa:
                    answer, cites, searched = wa, wc, True
            except Exception:
                pass
        if searched:
            web_used = True
            web_sources = [{
                "type": "web", "label": f"网络来源{i + 1}", "url": c.get("url", ""),
                "title": c.get("title", ""), "excerpt": c.get("title", ""),
            } for i, c in enumerate(cites[:10])]
        # 反哺检索：无论网络/资料库回答，用回答要点再查一次，命中则整合
        try:
            extra = _web_back_to_rag(answer, q, req.scope)
        except Exception:
            extra = []
        if not searched:
            # 资料库回答：仅当补充检索带来首轮没有的新章节才整合，普通问题不额外调用
            extra = [h for h in extra if not any(
                x.get("vol") == h.get("vol") and x.get("chapter") == h.get("chapter") for x in hits
            )]
        if extra:
            try:
                sys2, usr2 = build_prompt(q, extra, config.EXCERPT_CHARS)
                usr2 += ("\n\n注意：以上【参考资料】是补充检索的结果。若这些条目与本问题无关"
                         "（例如本问题涉及的不是《蛊真人》内容），请在回答开头明确写『资料库未收录相关内容』，"
                         "不要引用资料库条目编号，也不列『依据来源』行。"
                         "\n\n另附已有回答内容（仅供参考，不作为资料库依据）：\n" + answer[:600])
                merged = ask_llm(sys2, usr2, config.KEY, config.BASE_URL, config.MODEL, history=req.history)
                if merged and merged.strip() and not _supplement_irrelevant(merged):
                    combined = True
                    extra_sources = [format_source(h) for h in extra]
                    if web_used:
                        answer = "（首次检索未命中，以下为结合资料库补充检索与网络检索的整合回答）\n\n" + merged
                    else:
                        answer = "（补充检索到更多相关章节，以下为整合回答）\n\n" + merged
            except Exception:
                combined = False
        if web_used and not combined:
            answer = "（资料库未检索到相关内容，以下为**网络检索回答**，请自行核对来源）\n\n" + answer
        mock = False
    else:
        answer = mock_answer(hits)
        mock = True
    # 通用知识回答：不展示资料库来源卡片、LLM 编造的『依据来源』行与相关词条
    gen_knowledge = not web_used and not combined and (
        "资料库未检索到相关内容" in answer or "基于通用知识的回答" in answer
    )
    if gen_knowledge:
        lines = answer.rstrip().split("\n")
        while lines and lines[-1].strip().startswith("依据来源"):
            lines.pop()
        answer = "\n".join(lines).rstrip()
    if combined:
        shown_sources = extra_sources + web_sources
    elif web_used or gen_knowledge:
        shown_sources = web_sources
    else:
        shown_sources = [format_source(h) for h in hits] + web_sources
    # 相关词条：通用知识或网络回答时，从回答与问题中提取提及的百科词条（长名优先），让用户依然可以直接跳转百科
    wiki_cites = _wiki_cites_in(answer + " " + q)
    return {
        "answer": answer,
        "sources": shown_sources,
        "cost_rmb": estimate_cost(system, user, answer) if not mock else 0.0,
        "mock": mock,
        "web": web_used,
        "wiki_cites": wiki_cites,
    }


# ---------- 设置 ----------

@app.post("/api/settings")
def save_settings(req: SettingsReq):
    if req.api_key is not None:
        config.set_api_key(req.api_key)
    if req.base_url is not None:
        config.set_base_url(req.base_url)
    if req.model is not None:
        config.set_model(req.model)
    if req.embed_model is not None:
        config.set_data_dir(req.embed_model)
        try:
            reload_retriever()
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"模型切换失败：{e}"}, status_code=500)
    return {
        "ok": True, "has_key": bool(config.KEY), "base_url": config.BASE_URL,
        "model": config.MODEL,
        "data_dir": str(config.DATA_DIR), "embed_model": str(config.DATA_DIR),
    }


@app.post("/api/settings/test")
def test_settings(req: TestReq):
    key = (req.api_key or config.KEY or "").strip()
    base_url = (req.base_url or config.BASE_URL or "").strip()
    model = (req.model or config.MODEL or "").strip()
    if not key:
        return {"ok": False, "error": "还没有填写 API Key"}
    if not base_url:
        return {"ok": False, "error": "还没有填写 Base URL"}
    if not model:
        return {"ok": False, "error": "还没有填写模型名"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        return {
            "ok": True,
            "models": [resp.model or model],
            "message": "连接成功",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:300], "message": "连接失败"}


# ---------- 检索模型选项 ----------

@app.get("/api/models")
def list_models():
    import json as _json
    results = {}
    erp = Path(__file__).resolve().parent.parent / "eval_results.json"
    if erp.is_file():
        try:
            results = _json.loads(erp.read_text(encoding="utf-8"))
        except Exception:
            results = {}
    options = []
    label_map = {
        "data": "标准（bge-small-zh-v1.5，最快）",
        "data_m3": "更准（BGE-M3 1024维）",
        "data_jina2": "中文增强（jina-v2-base-zh）",
    }
    for key, rel in config.DATA_DIR_OPTIONS.items():
        d = config.BASE / rel
        info_p = d / "info.json"
        if not info_p.is_file():
            continue
        try:
            info = _json.loads(info_p.read_text(encoding="utf-8"))
        except Exception:
            continue
        ev = results.get(rel, {})
        options.append({
            "id": key, "dir": rel, "model": info.get("model", ""),
            "label": label_map.get(rel, rel),
            "dim": info.get("shapes", {}).get("novel", [0, 0])[1],
            "count": info.get("n", 0),
            "available": True,
            "hit5": ev.get("hit5"), "avg_query_s": ev.get("avg_query_s"),
            "current": rel == config.DATA_DIR.name,
        })
    return {"options": options, "current": config.DATA_DIR.name}


# ---------- 百科与游戏 ----------

_wiki = None
_quiz = None
_content_mtime = {}
_wiki_names = None
_wiki_names_mtime = None


def _wiki_name_index():
    """百科词条名 -> 分类 索引（按文件修改时间缓存）。"""
    global _wiki_names, _wiki_names_mtime
    mt = _content_mtime.get("wiki")
    if _wiki_names is not None and _wiki_names_mtime == mt:
        return _wiki_names
    d = {}
    for cat, items in (_wiki or {}).items():
        for e in items:
            n = e.get("name", "")
            if len(n) >= 2 and n not in d:
                d[n] = cat
    _wiki_names = d
    _wiki_names_mtime = mt
    return d


def _wiki_cites_in(text, limit=8):
    """在回答文本中找出命中的百科词条（长名优先），供前端跳转词条页。"""
    try:
        _load_content()  # 确保百科已加载
        idx = _wiki_name_index()
        names = sorted(idx.keys(), key=len, reverse=True)
        used = set()
        cites = []
        for n in names:
            if n in text and n not in used:
                cites.append({"name": n, "cat": idx[n]})
                used.add(n)
                if len(cites) >= limit:
                    break
        return cites
    except Exception:
        return []


def _load_content():
    """按文件修改时间热加载百科与题库（数据更新后无需重启服务）。"""
    global _wiki, _quiz, _content_mtime

    def _resolve(key):
        # 统一位置：data/ 为唯一权威文件；仅当不存在时回退到当前模型目录（历史兼容）
        p = config.BASE / "data" / f"{key}.json"
        if not p.is_file():
            alt = config.DATA_DIR / f"{key}.json"
            if alt.is_file():
                return alt
        return p

    targets = (
        ("wiki", _resolve("wiki"), "_wiki"),
        ("quiz", _resolve("quiz"), "_quiz"),
    )
    for key, path, slot in targets:
        try:
            mt = path.stat().st_mtime if path.is_file() else None
        except OSError:
            mt = None
        if _content_mtime.get(key) == mt:
            continue
        _content_mtime[key] = mt
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {} if key == "wiki" else {"quiz": [], "riddles": {}}
            if key == "wiki":
                _wiki = data
            else:
                _quiz = data
        else:
            if key == "wiki":
                _wiki = {}
            else:
                _quiz = {"quiz": [], "riddles": {}}


@app.get("/api/wiki")
def wiki_all():
    _load_content()
    return {
        "categories": {k: v for k, v in _wiki.items() if k not in ("其他", "_deleted")},
        "other": _wiki.get("其他", []),
        "stats": {k: len(v) for k, v in _wiki.items() if k != "_deleted"},
    }


class WikiEntryReq(BaseModel):
    cat: str | None = None          # 新分类（移动时）
    name: str | None = None         # 新名称（改名时）
    old_cat: str | None = None      # 原分类
    old_name: str | None = None     # 原名称
    sub: str | None = None
    section: str | None = None
    desc: str | None = None
    delete: bool = False


@app.post("/api/wiki/update")
def wiki_update(req: WikiEntryReq):
    """编辑/删除百科条目，直接写回资料库 wiki.json（所有数据目录同步）。"""
    _load_content()
    path = config.BASE / "data" / "wiki.json"
    if not path.is_file():
        return JSONResponse({"ok": False, "error": "资料库文件不存在"}, status_code=404)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"读取资料库失败：{e}"}, status_code=500)
    cat = req.old_cat or req.cat
    name = req.old_name or req.name
    entries = data.get(cat)
    if not isinstance(entries, list):
        return JSONResponse({"ok": False, "error": f"分类不存在：{cat}"}, status_code=404)
    idx = next((i for i, e in enumerate(entries) if e.get("name") == name), None)
    if idx is None:
        if req.delete:
            return JSONResponse({"ok": False, "error": f"条目不存在：{cat} / {name}"}, status_code=404)
        # ---- 新增词条 ----
        new_name = (req.name or "").strip()
        new_cat = req.cat or cat
        if not new_name:
            return JSONResponse({"ok": False, "error": "名称不能为空"}, status_code=400)
        entry = {
            "name": new_name,
            "desc": (req.desc or "").strip(),
            "section": (req.section or "").strip() or new_cat,
            "sub": (req.sub or "").strip(),
        }
        target = [e for e in data.get(new_cat, []) if e.get("name") != new_name]
        data[new_cat] = target
        target.append(entry)
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"写入资料库失败：{e}"}, status_code=500)
        _content_mtime["wiki"] = None
        return {"ok": True, "cat": new_cat, "entry": entry, "created": True}
    if req.delete:
        # 先进回收站，可恢复
        import time as _time
        entry = entries.pop(idx)
        trash = [t for t in data.get("_deleted", []) if not (t.get("cat") == cat and t.get("name") == entry.get("name"))]
        trash.append(dict(entry, cat=cat, deletedAt=round(_time.time())))
        data["_deleted"] = trash
        if not entries:
            data.pop(cat, None)
    else:
        entry = entries[idx]
        new_cat = req.cat or cat
        new_name = (req.name or name).strip()
        if not new_name:
            return JSONResponse({"ok": False, "error": "名称不能为空"}, status_code=400)
        if new_cat != cat or new_name != name:
            entries.pop(idx)
            target = [e for e in data.get(new_cat, []) if e.get("name") != new_name]
            data[new_cat] = target
            entry = dict(entry)
            entry["name"] = new_name
            target.append(entry)
        else:
            entry["name"] = new_name
        if req.sub is not None:
            entry["sub"] = req.sub.strip()
        if req.section is not None:
            entry["section"] = req.section.strip()
        if req.desc is not None:
            entry["desc"] = req.desc.strip()
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"写入资料库失败：{e}"}, status_code=500)
    _content_mtime["wiki"] = None  # 强制下次请求重新加载
    if req.delete:
        return {"ok": True, "deleted": 1}
    return {"ok": True, "cat": req.cat or cat, "entry": entry}


class WikiTrashReq(BaseModel):
    cat: str
    name: str


@app.get("/api/wiki/trash")
def wiki_trash_list():
    """回收站：被删除的词条。"""
    _load_content()
    return {"items": list(_wiki.get("_deleted", []))}


@app.post("/api/wiki/restore")
def wiki_restore(req: WikiTrashReq):
    """把回收站里的词条恢复到原分类。"""
    _load_content()
    path = config.BASE / "data" / "wiki.json"
    if not path.is_file():
        return JSONResponse({"ok": False, "error": "资料库文件不存在"}, status_code=404)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"读取资料库失败：{e}"}, status_code=500)
    trash = data.get("_deleted", [])
    idx = next((i for i, t in enumerate(trash) if t.get("cat") == req.cat and t.get("name") == req.name), None)
    if idx is None:
        return JSONResponse({"ok": False, "error": "回收站中找不到该词条"}, status_code=404)
    entry = dict(trash.pop(idx))
    entry.pop("cat", None)
    entry.pop("deletedAt", None)
    target = [e for e in data.get(req.cat, []) if e.get("name") != entry.get("name")]
    data[req.cat] = target
    target.append(entry)
    if not trash:
        data.pop("_deleted", None)
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"写入资料库失败：{e}"}, status_code=500)
    _content_mtime["wiki"] = None
    return {"ok": True, "entry": entry}


@app.post("/api/wiki/trash-purge")
def wiki_trash_purge(req: WikiTrashReq):
    """从回收站彻底删除（不可恢复）。"""
    _load_content()
    path = config.BASE / "data" / "wiki.json"
    if not path.is_file():
        return JSONResponse({"ok": False, "error": "资料库文件不存在"}, status_code=404)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"读取资料库失败：{e}"}, status_code=500)
    trash = [t for t in data.get("_deleted", []) if not (t.get("cat") == req.cat and t.get("name") == req.name)]
    data["_deleted"] = trash
    if not trash:
        data.pop("_deleted", None)
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"写入资料库失败：{e}"}, status_code=500)
    _content_mtime["wiki"] = None
    return {"ok": True, "purged": 1}


class QuizReq(BaseModel):
    type: str = "mix"   # mix / gu / person / type
    n: int = 10


@app.post("/api/quiz")
def quiz_pick(req: QuizReq):
    import random as _rnd
    _load_content()
    pool = _quiz["quiz"]
    if req.type == "gu":
        pool = [x for x in pool if x["type"] == "蛊虫"]
    elif req.type == "person":
        pool = [x for x in pool if x["type"] == "人物"]
    elif req.type == "type":
        pool = [x for x in pool if x["type"] == "蛊虫类型"]
    n = min(max(req.n, 1), 100)
    picked = _rnd.sample(pool, min(n, len(pool)))
    for i, p in enumerate(picked):
        p = dict(p)
        p["id"] = f"q{_rnd.randint(100000, 999999)}"
        picked[i] = p
    return {"questions": picked}


@app.get("/api/quiz/all")
def quiz_all():
    """返回默认题库全部题目文本与谜底名称（供自定义题库去重使用）。"""
    _load_content()
    return {
        "questions": [x["q"] for x in _quiz["quiz"]],
        "riddle_names": {k: [x["name"] for x in v] for k, v in _quiz["riddles"].items()},
    }


class RiddleReq(BaseModel):
    type: str = "gu"   # gu / person / item
    n: int = 1


@app.post("/api/riddle")
def riddle_pick(req: RiddleReq):
    import random as _rnd
    _load_content()
    pool = _quiz["riddles"].get(req.type, [])
    n = min(max(req.n, 1), 5)
    picked = _rnd.sample(pool, min(n, len(pool)))
    for i, p in enumerate(picked):
        p = dict(p)
        p["id"] = f"r{_rnd.randint(100000, 999999)}"
        picked[i] = p
    return {"riddles": picked}


# ---------- 阅读库 ----------

@app.get("/api/library")
def get_library():
    tocs = library.pdf_toc()
    pdfs = library.pdf_files()
    for p in pdfs:
        p["toc"] = tocs.get(p["name"], [])
    return {
        "volumes": library.novel_volumes(),
        "pdfs": pdfs,
        "lore": {
            "name": LORE_NAME,
            "html_url": "/api/lore/html",
            "download_url": "/api/lore/download",
        },
        "novel_root": str(library.NOVEL_ROOT),
    }


LORE_NAME = library.LORE_DOCX.name


@app.get("/api/lore/entry")
def lore_entry(section: str):
    """返回设定集某小节的完整内容（供来源卡片「阅读原文」）。"""
    p = config.DATA_DIR / "lore" / "meta.json"
    if not p.is_file():
        raise HTTPException(404, "设定库不存在")
    meta = json.loads(p.read_text(encoding="utf-8"))
    texts = [ch.get("text", "") for ch in meta if ch.get("section") == section]
    if not texts:
        raise HTTPException(404, "未找到该小节")
    return {"section": section, "text": "\n\n".join(texts)}


@app.get("/api/chapter")
def get_chapter(vol: str, chapter: int):
    r = library.chapter_text(vol, chapter)
    if r is None:
        raise HTTPException(404, "未找到该章节")
    return r


@app.post("/api/locate")
def locate(req: LocateReq):
    """在本地打开/定位原文 txt 文件（Windows）。"""
    r = library.chapter_text(req.vol, req.chapter)
    if r is None:
        raise HTTPException(404, "未找到该章节")
    path = r["path"]
    try:
        if os.name == "nt":
            os.startfile(path)  # 用默认应用打开 txt
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        return {"ok": False, "path": path, "error": str(e)}
    return {"ok": True, "path": path}


@app.post("/api/lore/search")
def search_lore_text(req: LoreSearchReq):
    """资料合集段落全文检索：支持普通文字与正则表达式。"""
    q = (req.query or "").strip()
    if not q:
        return {"results": [], "total_matches": 0, "query": q, "is_regex": req.is_regex}
    try:
        pattern = re.compile(q if req.is_regex else re.escape(q), re.IGNORECASE)
    except re.error as e:
        return JSONResponse({"error": f"正则表达式语法错误：{e}"}, status_code=400)
    if req.is_regex and pattern.search(""):
        return JSONResponse({"error": "正则表达式不能匹配空文本，请至少匹配一个字符"}, status_code=400)

    data = library.lore_structured()
    results, total_matches = [], 0
    section = data.get("title", "资料合集")
    limit = max(1, min(int(req.limit or 80), 200))
    for index, para in enumerate(data.get("paras", [])):
        text = str(para.get("text") or "")
        if para.get("kind") == "h2":
            section = text
        matches = list(pattern.finditer(text))
        if not matches:
            continue
        snippets = []
        for match in matches[:3]:
            start, end = max(0, match.start() - 44), min(len(text), match.end() + 88)
            snippets.append({"snippet": text[start:end], "match": match.group(0)})
        results.append({
            "index": index, "anchor": para.get("anchor", "") or f"lpara{index}",
            "section": section, "text": text, "count": len(matches), "snippets": snippets,
        })
        total_matches += len(matches)
        if len(results) >= limit:
            break
    return {"results": results, "total_matches": total_matches, "paragraphs_matched": len(results),
            "query": q, "is_regex": req.is_regex, "truncated": len(results) >= limit}


@app.get("/api/lore/data")
def lore_data():
    return library.lore_structured()


@app.get("/api/lore/html")
def lore_html():
    return HTMLResponse(library.lore_html())


@app.get("/api/lore/download")
def lore_download():
    if not library.LORE_DOCX.is_file():
        raise HTTPException(404, "资料合集不存在")
    return FileResponse(library.LORE_DOCX, filename=library.LORE_DOCX.name)
