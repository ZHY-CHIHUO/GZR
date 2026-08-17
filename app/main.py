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
        for _cat, _g, e in _iter_wiki_entries(_wiki or {}):
            if e.get("name") == c.get("name") and (c.get("cat") == _cat or entry is None):
                entry = e
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


def _is_active_wiki_hit(hit):
    """向量索引可能尚未重建；只允许当前权威 wiki.json 中仍存在的词条进入 RAG。"""
    if hit.get("type") != "wiki":
        return True
    try:
        _load_content()
        name, cat, sub = hit.get("name"), hit.get("cat"), hit.get("sub", "") or ""
        hit_path = hit.get("path")
        for current_cat, group_path, entry in _iter_wiki_paths(_wiki or {}):
            if current_cat != cat or entry.get("name") != name:
                continue
            if hit_path is not None:
                return list(hit_path) == group_path
            if not sub or "/".join(group_path) == sub or (group_path and group_path[-1] == sub):
                return True
        return False
    except Exception:
        return False


def _filter_stale_wiki_hits(hits):
    return [h for h in hits if _is_active_wiki_hit(h)]


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
    for cat, _g, entry in _iter_wiki_entries(_wiki or {}):
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

def _literal_text_query(question: str):
    """判断输入是否像一段待考据的连续文本，而不是常规语义提问。"""
    q = (question or "").strip()
    if not (4 <= len(q) <= 80):
        return None
    if re.search(r"[？?]|(?:谁|什么|为何|为什么|怎么|怎样|如何|多少|第几章|哪一章|哪里|在哪|是否)", q):
        return None
    # 纯短语/引文（可含逗号、句号）；避免把带长解释的自然语言问题做全书逐字扫描。
    return q if not re.search(r"[：:；;]", q) else None


def _exact_novel_evidence(query: str):
    """为连续文本提供确定性原著证据；唯一命中可直接定章，多命中交给 RAG 结合首处证据解释。"""
    try:
        found = _novel_text_search(query, limit=200)
    except ValueError:
        return None
    if not found.get("results"):
        return None
    evidence = []
    for item in found["results"][:3]:
        snip = (item.get("snippets") or [{}])[0]
        evidence.append({
            "type": "novel", "vol": item["vol"], "chapter": item["chapter"], "title": item["title"],
            "text": snip.get("snippet", ""), "_exact_text": True,
            "_exact_line": snip.get("line"),
        })
    return {"found": found, "evidence": evidence}


def _unique_exact_novel_response(query: str, evidence):
    """连续文本全书只命中一次时，直接返回唯一可复核章节而不是让模型猜。"""
    item = evidence["found"]["results"][0]
    snip = (item.get("snippets") or [{}])[0]
    line = snip.get("line")
    line_note = f"（原始文本第 {line} 行）" if line else ""
    answer = (f"“{query}”在本地《蛊真人》原著正文中只精确命中 **1 处**：\n\n"
              f"**{item['vol']} · 第 {item['chapter']} 章 · {item['title']}** {line_note}\n\n"
              f"> {snip.get('snippet', '')}\n\n"
              "结果由原著全文精确扫描得出，不依赖 RAG 相似度排序。")
    source = format_source(evidence["evidence"][0])
    source["label"] += "（全文唯一命中）"
    return {"answer": answer, "sources": [source],
            "exact_lookup": {"query": query, "found": True, "unique": True,
                             "total_matches": 1, "vol": item["vol"], "chapter": item["chapter"], "line": line}}


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

    # 连续文本先走全文考据：二创资料先定性；原著唯一命中直接给出章节；多处命中把最早几处原文证据交给 RAG。
    collection = _collection_poetry_response(q)
    if collection:
        return {**collection, "cost_rmb": 0.0, "mock": False, "web": False}
    literal = _literal_text_query(q)
    exact_novel = _exact_novel_evidence(literal) if literal else None
    if exact_novel and exact_novel["found"].get("total_matches") == 1:
        unique = _unique_exact_novel_response(literal, exact_novel)
        return {**unique, "cost_rmb": 0.0, "mock": False, "web": False,
                "wiki_cites": _wiki_cites_in(q)}
    # 一次检索（普通 + 追问增强 + 词条名强制召回 + 词条名原文补充）
    hits = _force_wiki_hits(q, retriever.search(search_q, scope=req.scope))
    # 词条在百科被删除后，即使旧向量仍暂存，也绝不能再作为 RAG 证据或来源卡片。
    hits = _filter_stale_wiki_hits(hits)
    if exact_novel:
        # 多次命中时，最早的实际原文排在 RAG 证据前面，模型不能再说“未收录”。
        seen = {(h.get("vol"), h.get("chapter")) for h in hits}
        hits = [h for h in exact_novel["evidence"] if (h.get("vol"), h.get("chapter")) not in seen] + hits
    exact_wiki = _exact_wiki_hits(q)
    for hit in exact_wiki:
        if not any(h.get("type") == "wiki" and h.get("name") == hit.get("name") and h.get("sub") == hit.get("sub") for h in hits):
            hits.insert(0, hit)
    hits = hits + _retry_extra(q, hits, req.scope)
    system, user = build_prompt(q, hits, config.EXCERPT_CHARS)
    if exact_novel:
        first = exact_novel["found"]["results"][0]
        count = exact_novel["found"]["total_matches"]
        user += (f"\n\n【全文精确核验】用户输入的连续文本在原著中已命中 {count} 处；"
                 f"按卷章顺序的首处是 {first['vol']}·第{first['chapter']}章《{first['title']}》。"
                 "回答必须承认该原文命中并优先说明首处；不要说资料库未收录，也不要联网搜索。")
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
    return {
        "ok": True, "has_key": bool(config.KEY), "base_url": config.BASE_URL,
        "model": config.MODEL,
        "data_dir": str(config.DATA_DIR), "embed_model": retriever.model_name if retriever else "",
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


# ---------- 百科与游戏 ----------


def _is_wiki_leaf(v):
    """词条节点：值为 dict 且带介绍字段（key 即词条名）。"""
    return isinstance(v, dict) and any(k in v for k in ("intro", "desc", "sections", "aliases"))


def _iter_wiki_entries(data):
    """兼容旧调用：递归遍历并 yield (cat, slash_group_path, entry)。"""
    for cat, group_path, entry in _iter_wiki_paths(data):
        yield cat, "/".join(group_path), entry


def _walk_wiki_nodes(cat, node, group_path):
    """遍历一个分类下任意深度的分组树。"""
    if not isinstance(node, dict):
        return
    for name, value in node.items():
        if not isinstance(value, dict):
            continue
        has_children = any(isinstance(child, dict) for child in value.values())
        if has_children:
            yield from _walk_wiki_nodes(cat, value, group_path + [str(name)])
        if _is_wiki_leaf(value):
            yield cat, group_path, {"name": name, **value}


def _iter_wiki_paths(data):
    """递归遍历百科，yield (category, group_path, entry)。"""
    if not isinstance(data, dict):
        return
    for cat, node in data.items():
        if not isinstance(node, dict) or cat == "_deleted":
            continue
        yield from _walk_wiki_nodes(cat, node, [])


def _flatten_wiki_tree(data):
    """树 -> 兼容旧前端的分类数组，并从实际路径派生元数据。"""
    flat = {}
    for cat, group_path, entry in _iter_wiki_paths(data):
        entry = dict(entry)
        entry["path"] = list(group_path)
        if group_path:
            entry.setdefault("sub", group_path[-1])
            entry["tier"] = group_path[-1]
            entry["source_path"] = " / ".join([cat] + group_path)
        else:
            entry.setdefault("sub", "其他")
            entry["tier"] = ""
            entry["source_path"] = cat
        flat.setdefault(cat, []).append(entry)
    return flat

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
    for cat, _g, e in _iter_wiki_entries(_wiki or {}):
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
        # 资料与向量库统一存放在固定的 Jina 数据目录。
        return config.DATA_DIR / f"{key}.json"

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
    flat = _flatten_wiki_tree(_wiki or {})
    tree = {k: v for k, v in (_wiki or {}).items() if k != "_deleted"}
    stats = {k: len(v) for k, v in flat.items()}
    groups = {}
    for cat, group_path, _entry in _iter_wiki_paths(_wiki or {}):
        if group_path:
            key = "/".join(group_path)
            bucket = groups.setdefault(cat, {})
            bucket[key] = bucket.get(key, 0) + 1
    return {
        "categories": {k: v for k, v in flat.items() if k not in ("其他", "_deleted")},
        "other": flat.get("其他", []),
        "tree": tree,
        "stats": stats,
        "groups": groups,
    }


@app.get("/api/wiki/search")
def wiki_search(q: str = "", cat: str = "", group: str = "", limit: int = 300):
    """按名称、别名和正文搜索百科树，返回带完整路径的词条。"""
    query = q.strip()
    if len(query) < 2:
        return {"items": [], "total": 0}
    _load_content()
    group_path = [p for p in group.split("/") if p]
    matches = []
    for current_cat, path_parts, raw_entry in _iter_wiki_paths(_wiki or {}):
        if cat and current_cat != cat:
            continue
        if group_path and path_parts != group_path:
            continue
        entry = dict(raw_entry)
        entry["path"] = list(path_parts)
        entry["sub"] = path_parts[-1] if path_parts else "其他"
        entry["tier"] = path_parts[-1] if path_parts else ""
        entry["source_path"] = " / ".join([current_cat] + path_parts)
        name = str(entry.get("name") or "")
        aliases = [str(a) for a in (entry.get("aliases") or [])]
        alias_exact = query in aliases
        if name == query:
            score = 0
        elif alias_exact:
            score = 1
        elif query in name:
            score = 2
        elif any(query in alias for alias in aliases):
            score = 3
        else:
            body = " ".join([
                str(entry.get("intro") or ""), str(entry.get("desc") or ""),
                " ".join(f"{s.get('title', '')} {s.get('text', '')}" for s in (entry.get("sections") or [])),
            ])
            if query not in body:
                continue
            score = 4
        matches.append((score, current_cat, path_parts, entry))
    matches.sort(key=lambda item: (item[0], item[1], item[2], item[3]["name"]))
    cap = min(max(limit, 1), 500)
    items = [{"cat": current_cat, **entry} for _score, current_cat, _path, entry in matches[:cap]]
    return {"items": items, "total": len(matches)}


class WikiEntryReq(BaseModel):
    cat: str | None = None
    name: str | None = None
    old_cat: str | None = None
    old_name: str | None = None
    path: list[str] | None = None
    old_path: list[str] | None = None
    sub: str | None = None
    section: str | None = None
    desc: str | None = None
    delete: bool = False


def _wiki_node_at(data, cat, group_path, create=False):
    if create and not isinstance(data.get(cat), dict):
        data[cat] = {}
    node = data.get(cat)
    if not isinstance(node, dict):
        return None
    for part in group_path:
        if create and not isinstance(node.get(part), dict):
            node[part] = {}
        node = node.get(part)
        if not isinstance(node, dict):
            return None
    return node


def _prune_wiki_groups(data, cat, group_path):
    for depth in range(len(group_path), 0, -1):
        parent = _wiki_node_at(data, cat, group_path[:depth - 1])
        child_name = group_path[depth - 1]
        if not isinstance(parent, dict) or not isinstance(parent.get(child_name), dict) or parent[child_name]:
            break
        parent.pop(child_name, None)
    if isinstance(data.get(cat), dict) and not data[cat]:
        data.pop(cat, None)


@app.post("/api/wiki/update")
def wiki_update(req: WikiEntryReq):
    """按分类与完整分组路径新增、编辑、移动或删除词条。"""
    _load_content()
    file_path = config.DATA_DIR / "wiki.json"
    if not file_path.is_file():
        return JSONResponse({"ok": False, "error": "资料库文件不存在"}, status_code=404)
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"读取资料库失败：{e}"}, status_code=500)

    old_cat, old_name = req.old_cat or req.cat, req.old_name or req.name
    old_path = list(req.old_path or [])
    parent = _wiki_node_at(data, old_cat, old_path) if old_cat and old_name else None
    entry = parent.get(old_name) if isinstance(parent, dict) else None
    if entry is not None and not _is_wiki_leaf(entry):
        entry = None

    if entry is None and req.delete:
        return JSONResponse({"ok": False, "error": "条目不存在"}, status_code=404)
    if entry is None:
        new_name = (req.name or "").strip()
        if not new_name:
            return JSONResponse({"ok": False, "error": "名称不能为空"}, status_code=400)
        target_cat = req.cat or old_cat
        target_path = list(req.path if req.path is not None else ([req.sub] if req.sub else []))
        target = _wiki_node_at(data, target_cat, target_path, create=True)
        if new_name in target:
            return JSONResponse({"ok": False, "error": "目标位置已有同名词条"}, status_code=409)
        entry = {"desc": (req.desc or "").strip()}
        if req.section:
            entry["section"] = req.section.strip()
        target[new_name] = entry
        result = {"ok": True, "cat": target_cat, "path": target_path, "entry": {"name": new_name, **entry}, "created": True}
    elif req.delete:
        import time as _time
        trash = list(data.get("_deleted", []))
        trash = [t for t in trash if not (t.get("cat") == old_cat and t.get("name") == old_name and t.get("path", []) == old_path)]
        trash.append({**entry, "name": old_name, "cat": old_cat, "path": old_path, "deletedAt": round(_time.time())})
        data["_deleted"] = trash
        parent.pop(old_name)
        _prune_wiki_groups(data, old_cat, old_path)
        result = {"ok": True, "deleted": 1}
    else:
        target_cat = req.cat or old_cat
        target_name = (req.name or old_name).strip()
        target_path = list(req.path if req.path is not None else (old_path if req.sub is None else ([req.sub] if req.sub else [])))
        if not target_name:
            return JSONResponse({"ok": False, "error": "名称不能为空"}, status_code=400)
        updated = dict(entry)
        if req.section is not None:
            updated["section"] = req.section.strip()
        if req.desc is not None:
            updated["desc"] = req.desc.strip()
        if (target_cat, target_path, target_name) != (old_cat, old_path, old_name):
            target = _wiki_node_at(data, target_cat, target_path, create=True)
            if target_name in target:
                return JSONResponse({"ok": False, "error": "目标位置已有同名词条"}, status_code=409)
            parent.pop(old_name)
            target[target_name] = updated
            _prune_wiki_groups(data, old_cat, old_path)
        else:
            parent[old_name] = updated
        result = {"ok": True, "cat": target_cat, "path": target_path, "entry": {"name": target_name, **updated}}
    try:
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"写入资料库失败：{e}"}, status_code=500)
    _content_mtime["wiki"] = None
    return result


class WikiTrashReq(BaseModel):
    cat: str
    name: str
    path: list[str] | None = None


@app.get("/api/wiki/trash")
def wiki_trash_list():
    _load_content()
    return {"items": list(_wiki.get("_deleted", []))}


def _take_trashed_entry(data, req):
    for index, item in enumerate(data.get("_deleted", [])):
        if item.get("cat") == req.cat and item.get("name") == req.name and (req.path is None or item.get("path", []) == req.path):
            return index, item
    return None, None


@app.post("/api/wiki/restore")
def wiki_restore(req: WikiTrashReq):
    _load_content()
    file_path = config.DATA_DIR / "wiki.json"
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"读取资料库失败：{e}"}, status_code=500)
    index, item = _take_trashed_entry(data, req)
    if item is None:
        return JSONResponse({"ok": False, "error": "回收站中找不到该词条"}, status_code=404)
    original_cat = item.get("cat")
    if not isinstance(original_cat, str) or not original_cat:
        return JSONResponse({"ok": False, "error": "回收站词条缺少原分类"}, status_code=500)
    target_path = list(item.get("path", []))
    target = _wiki_node_at(data, original_cat, target_path, create=True)
    if item["name"] in target:
        return JSONResponse({"ok": False, "error": "原位置已有同名词条"}, status_code=409)
    entry = {k: v for k, v in item.items() if k not in ("name", "cat", "path", "deletedAt")}
    target[item["name"]] = entry
    data["_deleted"].pop(index)
    if not data["_deleted"]:
        data.pop("_deleted")
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    _content_mtime["wiki"] = None
    return {"ok": True, "cat": original_cat, "path": target_path, "entry": {"name": item["name"], **entry}}


@app.post("/api/wiki/trash-purge")
def wiki_trash_purge(req: WikiTrashReq):
    _load_content()
    file_path = config.DATA_DIR / "wiki.json"
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"读取资料库失败：{e}"}, status_code=500)
    index, item = _take_trashed_entry(data, req)
    if item is None:
        return JSONResponse({"ok": False, "error": "回收站中找不到该词条"}, status_code=404)
    data["_deleted"].pop(index)
    if not data["_deleted"]:
        data.pop("_deleted")
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
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
