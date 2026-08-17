# -*- coding: utf-8 -*-
"""《蛊真人》RAG 本地网页服务。
启动：uvicorn app.main:app --port 8000
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, library
from .rag import Retriever, ask_llm, build_prompt, estimate_cost, format_source, mock_answer

APP_VERSION = "1.1.0"

retriever: Retriever | None = None
_wiki_index_job_lock = threading.Lock()
_wiki_index_job = {
    "state": "idle",
    "startedAt": "",
    "finishedAt": "",
    "durationSeconds": 0,
    "output": "",
    "error": "",
}


def reload_retriever():
    global retriever
    retriever = Retriever(config.DATA_DIR, config.MODEL_CACHE, top_k=config.TOP_K)


def _wiki_index_job_snapshot():
    with _wiki_index_job_lock:
        return dict(_wiki_index_job)


def _update_wiki_index_job(**changes):
    with _wiki_index_job_lock:
        _wiki_index_job.update(changes)


def _wiki_index_disk_status():
    wiki_path = config.DATA_DIR / "wiki.json"
    meta_path = config.DATA_DIR / "wiki" / "meta.json"
    vector_path = config.DATA_DIR / "wiki" / "vectors.npy"
    try:
        if not wiki_path.is_file() or not meta_path.is_file() or not vector_path.is_file():
            return {"available": False, "valid": False, "reason": "尚未建立百科索引"}
        wiki = json.loads(wiki_path.read_text(encoding="utf-8"))
        expected_meta = _wiki_index_metadata(wiki)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        vectors = np.load(vector_path, mmap_mode="r", allow_pickle=False)
        dimension = int(vectors.shape[1]) if vectors.ndim == 2 else 0
        entries = int(vectors.shape[0]) if vectors.ndim == 2 else 0
        if not isinstance(meta, list) or vectors.ndim != 2 or dimension != 768:
            return {"available": True, "valid": False, "entries": entries, "dimension": dimension,
                    "reason": "百科索引维度不为 768"}
        if len(meta) != entries or len(expected_meta) != entries:
            return {"available": True, "valid": False, "entries": entries, "dimension": dimension,
                    "reason": "百科索引条目数与当前资料不匹配"}
        if not _data_pack_same(meta, expected_meta):
            return {"available": True, "valid": False, "entries": entries, "dimension": dimension,
                    "reason": "百科索引与当前资料不匹配"}
        return {"available": True, "valid": True, "entries": entries, "dimension": dimension,
                "reason": "索引可用"}
    except Exception as e:
        return {"available": False, "valid": False, "reason": f"索引检查失败：{str(e)[:160]}"}


def _run_wiki_index_build():
    started = time.monotonic()
    command = [sys.executable, "scripts/build_wiki_store.py"]
    try:
        result = subprocess.run(
            command,
            cwd=config.BASE,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()[-6000:]
        duration = round(time.monotonic() - started, 1)
        if result.returncode != 0:
            _update_wiki_index_job(
                state="failed",
                finishedAt=datetime.now(timezone.utc).isoformat(),
                durationSeconds=duration,
                output=output,
                error=f"重建脚本退出码为 {result.returncode}",
            )
            return
        reload_retriever()
        index = _wiki_index_disk_status()
        if not index.get("valid"):
            _update_wiki_index_job(
                state="failed",
                finishedAt=datetime.now(timezone.utc).isoformat(),
                durationSeconds=duration,
                output=output,
                error=index.get("reason", "重建后的索引校验失败"),
            )
            return
        _update_wiki_index_job(
            state="completed",
            finishedAt=datetime.now(timezone.utc).isoformat(),
            durationSeconds=duration,
            output=output,
            error="",
        )
    except Exception as e:
        _update_wiki_index_job(
            state="failed",
            finishedAt=datetime.now(timezone.utc).isoformat(),
            durationSeconds=round(time.monotonic() - started, 1),
            error=str(e)[:600],
        )


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


@app.get("/api/wiki-index/status")
def wiki_index_status():
    return {"ok": True, "job": _wiki_index_job_snapshot(), "index": _wiki_index_disk_status()}


@app.post("/api/wiki-index/build")
def wiki_index_build():
    with _wiki_index_job_lock:
        if _wiki_index_job["state"] == "running":
            return JSONResponse({"ok": False, "error": "百科索引正在重建"}, status_code=409)
        _wiki_index_job.update({
            "state": "running",
            "startedAt": datetime.now(timezone.utc).isoformat(),
            "finishedAt": "",
            "durationSeconds": 0,
            "output": "",
            "error": "",
        })
    threading.Thread(target=_run_wiki_index_build, name="wiki-index-build", daemon=True).start()
    return {"ok": True, "job": _wiki_index_job_snapshot(), "index": _wiki_index_disk_status()}


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
        "customCategories": [name for name in _load_custom_wiki_categories() if name in tree],
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


class WikiCategoryReq(BaseModel):
    name: str | None = None


def _wiki_category_meta_path():
    return config.DATA_DIR / "wiki_categories.json"


def _load_custom_wiki_categories():
    try:
        payload = json.loads(_wiki_category_meta_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    categories = payload.get("custom") if isinstance(payload, dict) else None
    if not isinstance(categories, list):
        return []
    return list(dict.fromkeys(name for name in categories if isinstance(name, str) and name))


def _save_custom_wiki_categories(categories):
    _wiki_category_meta_path().write_text(
        json.dumps({"custom": list(dict.fromkeys(categories))}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def _normalize_wiki_category_name(name):
    value = str(name or "").strip()
    if not value:
        return None, "分类名称不能为空"
    if len(value) > 40:
        return None, "分类名称不能超过 40 个字符"
    if value.startswith("_") or any(token in value for token in ("/", "\\", "\n", "\r", "\x00")):
        return None, "分类名称包含不允许的字符"
    return value, None


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
    # Keep the top-level category even after its final entry is removed.  This
    # preserves existing categories and lets an empty custom category be
    # explicitly managed through the category API.


@app.post("/api/wiki/categories")
def wiki_category_create(req: WikiCategoryReq):
    name, error = _normalize_wiki_category_name(req.name)
    if error:
        return JSONResponse({"ok": False, "error": error}, status_code=400)
    _load_content()
    file_path = config.DATA_DIR / "wiki.json"
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"读取资料库失败：{e}"}, status_code=500)
    if name in data:
        return JSONResponse({"ok": False, "error": "分类已存在"}, status_code=409)

    custom_categories = _load_custom_wiki_categories()
    data[name] = {}
    try:
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        _save_custom_wiki_categories([*custom_categories, name])
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"写入分类失败：{e}"}, status_code=500)
    _content_mtime["wiki"] = None
    return {"ok": True, "category": name}


@app.post("/api/wiki/categories/delete")
def wiki_category_delete(req: WikiCategoryReq):
    name, error = _normalize_wiki_category_name(req.name)
    if error:
        return JSONResponse({"ok": False, "error": error}, status_code=400)
    _load_content()
    custom_categories = _load_custom_wiki_categories()
    if name not in custom_categories:
        return JSONResponse({"ok": False, "error": "现有分类受保护，不能删除"}, status_code=403)
    file_path = config.DATA_DIR / "wiki.json"
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"读取资料库失败：{e}"}, status_code=500)
    category = data.get(name)
    if category is None:
        return JSONResponse({"ok": False, "error": "分类不存在"}, status_code=404)
    if not isinstance(category, dict):
        return JSONResponse({"ok": False, "error": "分类数据格式错误"}, status_code=409)
    if category:
        return JSONResponse({"ok": False, "error": "分类仍有词条，清空后才能删除"}, status_code=409)

    data.pop(name)
    try:
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        _save_custom_wiki_categories([item for item in custom_categories if item != name])
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"删除分类失败：{e}"}, status_code=500)
    _content_mtime["wiki"] = None
    return {"ok": True, "category": name, "deleted": 1}


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

    if (req.old_cat is not None or req.old_name is not None) and req.old_path is None:
        return JSONResponse({"ok": False, "error": "编辑请求缺少旧路径"}, status_code=400)
    if req.delete and req.old_path is None and req.path is None:
        return JSONResponse({"ok": False, "error": "删除请求缺少完整路径"}, status_code=400)

    old_cat, old_name = req.old_cat or req.cat, req.old_name or req.name
    old_path = list(req.old_path if req.old_path is not None else (req.path or []))
    parent = _wiki_node_at(data, old_cat, old_path) if old_cat and old_name else None
    entry = parent.get(old_name) if isinstance(parent, dict) else None
    if entry is not None and not _is_wiki_leaf(entry):
        entry = None

    # Requests carrying an old identity are edits/moves, never creates.  A
    # stale or incomplete old path must fail loudly instead of silently adding
    # a second entry at the requested target path.
    if entry is None and (req.delete or req.old_cat is not None or req.old_name is not None):
        return JSONResponse({"ok": False, "error": "条目不存在"}, status_code=404)
    if entry is None:
        new_name = (req.name or "").strip()
        if not new_name:
            return JSONResponse({"ok": False, "error": "名称不能为空"}, status_code=400)
        target_cat = req.cat or old_cat
        if target_cat == "_deleted" or not isinstance(data.get(target_cat), dict):
            return JSONResponse({"ok": False, "error": "分类不存在，请先新增分类"}, status_code=404)
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
        target_path = list(req.path if req.path is not None else old_path)
        if not target_name:
            return JSONResponse({"ok": False, "error": "名称不能为空"}, status_code=400)
        if target_cat == "_deleted" or not isinstance(data.get(target_cat), dict):
            return JSONResponse({"ok": False, "error": "目标分类不存在，请先新增分类"}, status_code=404)
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
    path: list[str]


@app.get("/api/wiki/trash")
def wiki_trash_list():
    _load_content()
    return {"items": list(_wiki.get("_deleted", []))}


def _take_trashed_entry(data, req):
    for index, item in enumerate(data.get("_deleted", [])):
        if item.get("cat") == req.cat and item.get("name") == req.name and item.get("path", []) == req.path:
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


DATA_PACK_FORMAT = "gzr-data-pack"
DATA_PACK_VERSION = 1
DATA_PACK_MAX_BYTES = 128 * 1024 * 1024
DATA_PACK_EDITABLE_PATHS = {
    "data/wiki.json",
    "data/wiki_categories.json",
    "data/quiz.json",
    "data/wiki/meta.json",
    "data/wiki/vectors.npy",
    "browser/custom_quiz.json",
}


class DataPackExportReq(BaseModel):
    kind: str = "editable"
    custom_quiz: list = []


def _data_pack_sha256(payload):
    return hashlib.sha256(payload).hexdigest()


def _data_pack_json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8")


def _data_pack_json(payload, label):
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError) as e:
        raise ValueError(f"{label} 不是有效 JSON：{e}") from e


def _data_pack_read_json_file(name, fallback):
    path = config.DATA_DIR / name
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def _data_pack_wiki_entries(data):
    return sum(1 for _cat, _path, _entry in _iter_wiki_paths(data if isinstance(data, dict) else {}))


def _data_pack_safe_member(name, kind):
    if not isinstance(name, str) or not name or "\\" in name or name.startswith("/"):
        return False
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    if kind == "editable":
        return name in DATA_PACK_EDITABLE_PATHS
    if name == "browser/custom_quiz.json":
        return True
    return name.startswith("data/") and Path(name).suffix.lower() in {".json", ".npy"}


def _data_pack_source_files(kind, custom_quiz):
    if kind not in ("editable", "full"):
        raise ValueError("资料包类型无效")
    files = {}
    if kind == "editable":
        for relative in ("wiki.json", "wiki_categories.json", "quiz.json", "wiki/meta.json", "wiki/vectors.npy"):
            path = config.DATA_DIR / relative
            if path.is_file():
                files[f"data/{relative}"] = path.read_bytes()
    else:
        for path in config.DATA_DIR.rglob("*"):
            if path.is_file():
                relative = path.relative_to(config.DATA_DIR).as_posix()
                if Path(relative).suffix.lower() in {".json", ".npy"}:
                    files[f"data/{relative}"] = path.read_bytes()
    if "data/wiki.json" not in files or "data/quiz.json" not in files:
        raise ValueError("当前资料库缺少 wiki.json 或 quiz.json")
    files["browser/custom_quiz.json"] = _data_pack_json_bytes(custom_quiz if isinstance(custom_quiz, list) else [])
    return files


def _build_data_pack(kind, custom_quiz):
    files = _data_pack_source_files(kind, custom_quiz)
    wiki = _data_pack_json(files["data/wiki.json"], "wiki.json")
    info = _data_pack_read_json_file("info.json", {})
    wiki_sha = _data_pack_sha256(files["data/wiki.json"])
    has_wiki_index = {"data/wiki/meta.json", "data/wiki/vectors.npy"}.issubset(files)
    manifest = {
        "format": DATA_PACK_FORMAT,
        "version": DATA_PACK_VERSION,
        "kind": kind,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "model": info.get("model", ""),
        "wiki": {"sha256": wiki_sha, "entries": _data_pack_wiki_entries(wiki)},
        "wikiIndex": {
            "included": has_wiki_index,
            "sourceSha256": wiki_sha if has_wiki_index else "",
            "dimension": 768 if has_wiki_index else 0,
        },
        "files": [
            {"path": name, "sha256": _data_pack_sha256(payload), "bytes": len(payload)}
            for name, payload in sorted(files.items())
        ],
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", _data_pack_json_bytes(manifest))
        for name, payload in sorted(files.items()):
            archive.writestr(name, payload)
    return stream.getvalue()


def _load_data_pack(payload):
    if not payload or len(payload) > DATA_PACK_MAX_BYTES:
        raise ValueError("资料包为空或超过 128 MB 限制")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as e:
        raise ValueError("不是有效的资料包 ZIP 文件") from e
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if any(info.flag_bits & 0x1 for info in infos):
            raise ValueError("资料包不能包含加密文件")
        if sum(info.file_size for info in infos) > DATA_PACK_MAX_BYTES:
            raise ValueError("资料包解压后的数据超过 128 MB 限制")
        names = {info.filename for info in infos}
        if "manifest.json" not in names:
            raise ValueError("资料包缺少 manifest.json")
        manifest = _data_pack_json(archive.read("manifest.json"), "manifest.json")
        if not isinstance(manifest, dict) or manifest.get("format") != DATA_PACK_FORMAT:
            raise ValueError("资料包格式不受支持")
        if manifest.get("version") != DATA_PACK_VERSION:
            raise ValueError("资料包版本不兼容")
        kind = manifest.get("kind")
        if kind not in ("editable", "full"):
            raise ValueError("资料包类型无效")
        listed = manifest.get("files")
        if not isinstance(listed, list) or not listed:
            raise ValueError("资料包文件清单无效")
        listed_paths = set()
        for item in listed:
            if not isinstance(item, dict):
                raise ValueError("资料包文件清单无效")
            name = item.get("path")
            if not _data_pack_safe_member(name, kind) or name in listed_paths:
                raise ValueError("资料包包含不允许的文件")
            listed_paths.add(name)
        if names != listed_paths | {"manifest.json"}:
            raise ValueError("资料包文件与清单不一致")
        files = {}
        for item in listed:
            name = item["path"]
            raw = archive.read(name)
            if item.get("bytes") != len(raw) or item.get("sha256") != _data_pack_sha256(raw):
                raise ValueError(f"资料包文件校验失败：{name}")
            files[name] = raw
    if "data/wiki.json" not in files or "data/quiz.json" not in files:
        raise ValueError("资料包缺少百科或题库数据")
    wiki = _data_pack_json(files["data/wiki.json"], "wiki.json")
    quiz = _data_pack_json(files["data/quiz.json"], "quiz.json")
    if not isinstance(wiki, dict) or not isinstance(quiz, dict):
        raise ValueError("百科或题库数据格式无效")
    custom_quiz = _data_pack_json(files.get("browser/custom_quiz.json", b"[]"), "自定义题库")
    if not isinstance(custom_quiz, list):
        raise ValueError("自定义题库格式无效")
    if kind == "full":
        if "data/info.json" not in files:
            raise ValueError("完整离线包缺少 info.json")
        for name, raw in files.items():
            if name.endswith(".npy"):
                try:
                    np.load(io.BytesIO(raw), allow_pickle=False)
                except Exception as e:
                    raise ValueError(f"向量文件无效：{name}") from e
        incoming_info = _data_pack_json(files["data/info.json"], "info.json")
        current_info = _data_pack_read_json_file("info.json", {})
        if incoming_info.get("model") != current_info.get("model"):
            raise ValueError("完整离线包的向量模型与当前项目不一致")
    return manifest, files


def _wiki_identity_map(data):
    entries = {}
    for cat, path, entry in _iter_wiki_paths(data if isinstance(data, dict) else {}):
        name = str(entry.get("name") or "")
        if name:
            entries[(cat, tuple(path), name)] = {key: value for key, value in entry.items() if key != "name"}
    return entries


def _wiki_index_metadata(data):
    """Recreate the metadata written by scripts/build_wiki_store.py.

    A matching vector count is not enough: edited descriptions can leave the
    count unchanged while making every embedding stale.
    """

    docs = []
    for cat, path, entry in _iter_wiki_paths(data if isinstance(data, dict) else {}):
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        parts = []
        if entry.get("intro"):
            parts.append(str(entry["intro"]).strip())
        for section in entry.get("sections") or []:
            if not isinstance(section, dict):
                continue
            text = str(section.get("text") or "").strip()
            if text:
                parts.append(text)
        if not parts:
            desc = str(entry.get("desc") or "").strip()
            if not desc:
                continue
            parts.append(desc)
        sub = path[-1] if path else "其他"
        tier = path[-1] if path else ""
        aliases = [str(value).strip() for value in (entry.get("aliases") or []) if str(value).strip()]
        text = name + "：" + "\n".join(parts)
        if aliases:
            text += "（别名：" + "、".join(aliases) + "）"
        if tier and tier != "其他":
            text += "【" + tier + "】"
        elif sub and sub != "其他":
            text += "（" + sub + "）"
        docs.append({
            "type": "wiki",
            "name": name,
            "cat": cat,
            "path": path,
            "sub": sub,
            "tier": tier,
            "aliases": aliases,
            "section": entry.get("section") or "",
            "source_path": " / ".join([cat] + path),
            "text": text,
        })
    return docs


def _data_pack_same(left, right):
    return json.dumps(left, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _validate_data_pack_wiki_index(manifest, files):
    required = {"data/wiki/meta.json", "data/wiki/vectors.npy"}
    if not required.issubset(files):
        return {"included": False, "usable": False, "reason": "未包含百科索引"}
    wiki_sha = _data_pack_sha256(files["data/wiki.json"])
    descriptor = manifest.get("wikiIndex") if isinstance(manifest.get("wikiIndex"), dict) else {}
    if descriptor.get("sourceSha256") != wiki_sha or manifest.get("wiki", {}).get("sha256") != wiki_sha:
        return {"included": True, "usable": False, "reason": "索引与百科正文哈希不匹配"}
    current_info = _data_pack_read_json_file("info.json", {})
    if manifest.get("model") != current_info.get("model"):
        return {"included": True, "usable": False, "reason": "索引模型与当前项目不一致"}
    try:
        meta = _data_pack_json(files["data/wiki/meta.json"], "百科索引元数据")
        vectors = np.load(io.BytesIO(files["data/wiki/vectors.npy"]), allow_pickle=False)
    except Exception:
        return {"included": True, "usable": False, "reason": "百科索引文件无效"}
    expected_meta = _wiki_index_metadata(_data_pack_json(files["data/wiki.json"], "wiki.json"))
    if not isinstance(meta, list) or vectors.ndim != 2 or vectors.shape[1] != 768:
        return {"included": True, "usable": False, "reason": "百科索引维度不为 768"}
    if len(meta) != vectors.shape[0] or len(meta) != len(expected_meta):
        return {"included": True, "usable": False, "reason": "百科索引条目数不匹配"}
    if not _data_pack_same(meta, expected_meta):
        return {"included": True, "usable": False, "reason": "百科索引内容与百科正文不匹配"}
    return {"included": True, "usable": True, "reason": "索引可直接启用", "entries": len(expected_meta), "dimension": 768}


def _data_pack_preview(manifest, files):
    incoming_wiki = _data_pack_json(files["data/wiki.json"], "wiki.json")
    current_wiki = _data_pack_read_json_file("wiki.json", {})
    incoming_quiz = _data_pack_json(files["data/quiz.json"], "quiz.json")
    current_quiz = _data_pack_read_json_file("quiz.json", {"quiz": [], "riddles": {}})
    incoming_entries = _wiki_identity_map(incoming_wiki)
    current_entries = _wiki_identity_map(current_wiki)
    wiki_preview = _data_pack_entry_preview(
        incoming_entries,
        current_entries,
        lambda identity, _value: {"cat": identity[0], "path": list(identity[1]), "name": identity[2]},
    )
    incoming_quiz_entries = _quiz_identity_map(incoming_quiz)
    current_quiz_entries = _quiz_identity_map(current_quiz)
    quiz_preview = _data_pack_entry_preview(
        incoming_quiz_entries,
        current_quiz_entries,
        lambda identity, value: {"kind": identity[0], "type": value.get("type", identity[1]), "name": identity[2]},
    )
    return {
        "kind": manifest["kind"],
        "createdAt": manifest.get("createdAt", ""),
        "files": [{"path": item["path"], "bytes": item["bytes"]} for item in manifest["files"]],
        "wiki": wiki_preview,
        "quiz": quiz_preview,
        "customQuizEntries": len(_data_pack_json(files.get("browser/custom_quiz.json", b"[]"), "自定义题库")),
        "wikiIndex": _validate_data_pack_wiki_index(manifest, files),
    }


def _data_pack_entry_preview(incoming, current, sample_for):
    added = identical = conflicts = 0
    samples = []
    for identity, incoming_value in incoming.items():
        current_value = current.get(identity)
        if current_value is None:
            added += 1
        elif _data_pack_same(current_value, incoming_value):
            identical += 1
        else:
            conflicts += 1
            if len(samples) < 12:
                samples.append(sample_for(identity, incoming_value))
    return {
        "incomingEntries": len(incoming),
        "localEntries": len(current),
        "newEntries": added,
        "identicalEntries": identical,
        "conflicts": conflicts,
        "conflictSamples": samples,
    }


def _quiz_identity_map(data):
    entries = {}
    if not isinstance(data, dict):
        return entries
    for item in data.get("quiz", []):
        if isinstance(item, dict) and item.get("q"):
            entries[("quiz", "", str(item["q"]))] = item
    for kind, values in data.get("riddles", {}).items():
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict) and item.get("name"):
                entries[("riddle", str(kind), str(item["name"]))] = item
    return entries


def _merge_wiki_data(current, incoming):
    merged = json.loads(json.dumps(current, ensure_ascii=False))
    stats = {"added": 0, "identical": 0, "conflicts": 0}
    for cat, node in incoming.items():
        if cat != "_deleted" and isinstance(node, dict) and not isinstance(merged.get(cat), dict):
            merged[cat] = {}
    for cat, path, entry in _iter_wiki_paths(incoming):
        parent = _wiki_node_at(merged, cat, path, create=True)
        name = entry["name"]
        candidate = {key: value for key, value in entry.items() if key != "name"}
        existing = parent.get(name)
        if existing is None:
            parent[name] = candidate
            stats["added"] += 1
        elif _data_pack_same(existing, candidate):
            stats["identical"] += 1
        else:
            stats["conflicts"] += 1
    trash = list(merged.get("_deleted", []))
    known = {
        (item.get("cat"), tuple(item.get("path", [])), item.get("name"), item.get("deletedAt"))
        for item in trash if isinstance(item, dict)
    }
    for item in incoming.get("_deleted", []):
        if not isinstance(item, dict):
            continue
        key = (item.get("cat"), tuple(item.get("path", [])), item.get("name"), item.get("deletedAt"))
        if key not in known:
            trash.append(item)
            known.add(key)
    if trash:
        merged["_deleted"] = trash
    return merged, stats


def _merge_quiz_data(current, incoming):
    merged = json.loads(json.dumps(current, ensure_ascii=False))
    merged.setdefault("quiz", [])
    merged.setdefault("riddles", {})
    stats = {"added": 0, "conflicts": 0}
    quiz_by_question = {item.get("q"): item for item in merged["quiz"] if isinstance(item, dict) and item.get("q")}
    for item in incoming.get("quiz", []):
        if not isinstance(item, dict) or not item.get("q"):
            continue
        existing = quiz_by_question.get(item["q"])
        if existing is None:
            merged["quiz"].append(item)
            quiz_by_question[item["q"]] = item
            stats["added"] += 1
        elif not _data_pack_same(existing, item):
            stats["conflicts"] += 1
    for kind, values in incoming.get("riddles", {}).items():
        if not isinstance(values, list):
            continue
        target = merged["riddles"].setdefault(kind, [])
        by_name = {item.get("name"): item for item in target if isinstance(item, dict) and item.get("name")}
        for item in values:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            existing = by_name.get(item["name"])
            if existing is None:
                target.append(item)
                by_name[item["name"]] = item
                stats["added"] += 1
            elif not _data_pack_same(existing, item):
                stats["conflicts"] += 1
    return merged, stats


def _category_names_from_payload(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("custom"), list):
        return []
    return [name for name in payload["custom"] if isinstance(name, str) and name]


def _merge_category_meta(current_wiki, merged_wiki, current_meta, incoming_meta):
    existing_categories = {name for name, value in current_wiki.items() if name != "_deleted" and isinstance(value, dict)}
    names = list(dict.fromkeys(_category_names_from_payload(current_meta)))
    for name in _category_names_from_payload(incoming_meta):
        if name in names or name not in merged_wiki or name == "_deleted":
            continue
        if name not in existing_categories:
            names.append(name)
    return {"custom": names}


def _data_pack_backup():
    backup_dir = config.BASE / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"data-before-import-{stamp}.zip"
    suffix = 2
    while backup_path.exists():
        backup_path = backup_dir / f"data-before-import-{stamp}-{suffix}.zip"
        suffix += 1
    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in config.DATA_DIR.rglob("*"):
            if path.is_file():
                archive.write(path, f"data/{path.relative_to(config.DATA_DIR).as_posix()}")
    return str(backup_path.relative_to(config.BASE))


def _data_pack_write_member(relative, payload):
    root = config.DATA_DIR.resolve()
    target = (root / relative).resolve()
    if root not in target.parents:
        raise ValueError("资料包目标路径无效")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".import-tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, target)


def _data_pack_remove_member(relative):
    root = config.DATA_DIR.resolve()
    target = (root / relative).resolve()
    if root not in target.parents:
        raise ValueError("资料包目标路径无效")
    if target.is_file():
        target.unlink()


def _data_pack_remove_missing_full_members(files):
    included = {
        name.removeprefix("data/")
        for name in files
        if name.startswith("data/")
    }
    for path in config.DATA_DIR.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".json", ".npy"}:
            continue
        relative = path.relative_to(config.DATA_DIR).as_posix()
        if relative not in included:
            _data_pack_remove_member(relative)


def _apply_data_pack(manifest, files, mode):
    if mode not in ("merge", "replace"):
        raise ValueError("导入方式无效")
    kind = manifest["kind"]
    if kind == "full" and mode != "replace":
        raise ValueError("完整离线包只能覆盖导入")
    incoming_wiki = _data_pack_json(files["data/wiki.json"], "wiki.json")
    incoming_quiz = _data_pack_json(files["data/quiz.json"], "quiz.json")
    incoming_categories = _data_pack_json(files.get("data/wiki_categories.json", b"{}"), "分类数据")
    index = _validate_data_pack_wiki_index(manifest, files)
    backup = _data_pack_backup()
    wiki_changed = False
    index_installed = False
    summary = {"wikiAdded": 0, "wikiConflicts": 0, "quizAdded": 0, "quizConflicts": 0}
    if mode == "replace":
        for name, raw in files.items():
            if not name.startswith("data/"):
                continue
            relative = name.removeprefix("data/")
            if name in {"data/wiki/meta.json", "data/wiki/vectors.npy"} and not index["usable"]:
                continue
            _data_pack_write_member(relative, raw)
        if kind == "full":
            _data_pack_remove_missing_full_members(files)
        if kind == "editable" and "data/wiki_categories.json" not in files:
            _data_pack_remove_member("wiki_categories.json")
        if not index["usable"]:
            _data_pack_remove_member("wiki/meta.json")
            _data_pack_remove_member("wiki/vectors.npy")
        wiki_changed = True
        index_installed = bool(index["usable"])
    else:
        current_wiki = _data_pack_read_json_file("wiki.json", {})
        current_quiz = _data_pack_read_json_file("quiz.json", {"quiz": [], "riddles": {}})
        current_categories = _data_pack_read_json_file("wiki_categories.json", {})
        merged_wiki, wiki_stats = _merge_wiki_data(current_wiki, incoming_wiki)
        merged_quiz, quiz_stats = _merge_quiz_data(current_quiz, incoming_quiz)
        merged_categories = _merge_category_meta(current_wiki, merged_wiki, current_categories, incoming_categories)
        _data_pack_write_member("wiki.json", _data_pack_json_bytes(merged_wiki))
        _data_pack_write_member("quiz.json", _data_pack_json_bytes(merged_quiz))
        _data_pack_write_member("wiki_categories.json", _data_pack_json_bytes(merged_categories))
        summary.update({
            "wikiAdded": wiki_stats["added"],
            "wikiConflicts": wiki_stats["conflicts"],
            "quizAdded": quiz_stats["added"],
            "quizConflicts": quiz_stats["conflicts"],
        })
        wiki_changed = bool(wiki_stats["added"])
    _content_mtime["wiki"] = None
    _content_mtime["quiz"] = None
    reload_error = ""
    if index_installed or kind == "full" or mode == "replace":
        try:
            reload_retriever()
        except Exception as e:
            reload_error = str(e)
    return {
        "backup": backup,
        "summary": summary,
        "customQuiz": _data_pack_json(files.get("browser/custom_quiz.json", b"[]"), "自定义题库"),
        "indexInstalled": index_installed,
        "needsWikiRebuild": wiki_changed and not index_installed,
        "reloadError": reload_error,
    }


@app.post("/api/data-pack/export")
def data_pack_export(req: DataPackExportReq):
    try:
        payload = _build_data_pack(req.kind, req.custom_quiz)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"gzr-{req.kind}-{stamp}.gzrpack"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(io.BytesIO(payload), media_type="application/zip", headers=headers)


@app.post("/api/data-pack/inspect")
async def data_pack_inspect(request: Request):
    try:
        manifest, files = _load_data_pack(await request.body())
        return {"ok": True, "preview": _data_pack_preview(manifest, files)}
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.post("/api/data-pack/import")
async def data_pack_import(request: Request):
    try:
        manifest, files = _load_data_pack(await request.body())
        result = _apply_data_pack(manifest, files, request.headers.get("x-gzr-import-mode", "merge"))
        return {"ok": True, **result}
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"导入失败：{e}"}, status_code=500)


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
