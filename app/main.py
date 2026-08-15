# -*- coding: utf-8 -*-
"""《蛊真人》RAG 本地网页服务。
启动：uvicorn app.main:app --port 8000
"""
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import config, library
from .rag import Retriever, ask_llm, build_prompt, estimate_cost, format_source, mock_answer

retriever: Retriever | None = None


def reload_retriever():
    global retriever
    retriever = Retriever(config.DATA_DIR, config.MODEL_CACHE, top_k=config.TOP_K)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    reload_retriever()
    yield


app = FastAPI(title="蛊真人 RAG", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class AskReq(BaseModel):
    question: str
    scope: str = "all"          # all / novel / lore
    history: list = []          # [{role, content}, ...]


class SettingsReq(BaseModel):
    api_key: str | None = None
    model: str | None = None
    embed_model: str | None = None   # small / m3 / jina


class TestReq(BaseModel):
    api_key: str | None = None


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
        "model": config.MODEL,
        "embed_model": retriever.model_name,
        "stores": {name: s.n for name, s in retriever.stores.items()},
        "top_k": config.TOP_K,
        "data_dir": config.DATA_DIR.name,
    }


@app.post("/api/ask")
def ask(req: AskReq):
    q = (req.question or "").strip()
    if not q:
        return JSONResponse({"error": "问题不能为空"}, status_code=400)
    if retriever is None:
        return JSONResponse({"error": "检索库未加载"}, status_code=503)
    hits = retriever.search(q, scope=req.scope)
    system, user = build_prompt(q, hits, config.EXCERPT_CHARS)
    if config.KEY:
        try:
            answer = ask_llm(system, user, config.KEY, config.BASE_URL, config.MODEL, history=req.history)
        except Exception as e:
            return JSONResponse({"error": f"AI 调用失败：{e}"}, status_code=502)
        mock = False
    else:
        answer = mock_answer(hits)
        mock = True
    return {
        "answer": answer,
        "sources": [format_source(h) for h in hits],
        "cost_rmb": estimate_cost(system, user, answer) if not mock else 0.0,
        "mock": mock,
    }


# ---------- 设置 ----------

@app.post("/api/settings")
def save_settings(req: SettingsReq):
    if req.api_key is not None:
        config.set_api_key(req.api_key)
    if req.model is not None:
        config.set_model(req.model)
    if req.embed_model is not None:
        config.set_data_dir(req.embed_model)
        try:
            reload_retriever()
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"模型切换失败：{e}"}, status_code=500)
    return {
        "ok": True, "has_key": bool(config.KEY), "model": config.MODEL,
        "data_dir": str(config.DATA_DIR), "embed_model": str(config.DATA_DIR),
    }


@app.post("/api/settings/test")
def test_settings(req: TestReq):
    key = (req.api_key or config.KEY or "").strip()
    if not key:
        return {"ok": False, "error": "还没有填写 API Key"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=config.BASE_URL)
        try:
            models = client.models.list()
            names = [m.id for m in models.data][:6]
        except Exception:
            # 有些代理不支持 /models，退化为一次极小的对话测试
            resp = client.chat.completions.create(
                model=config.MODEL, max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
            names = [resp.model]
        return {"ok": True, "models": names, "message": "连接成功"}
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


def _load_content():
    global _wiki, _quiz
    if _wiki is None:
        wp = config.DATA_DIR / "wiki.json"
        if wp.is_file():
            _wiki = json.loads(wp.read_text(encoding="utf-8"))
        else:
            _wiki = {}
    if _quiz is None:
        qp = config.DATA_DIR / "quiz.json"
        if qp.is_file():
            _quiz = json.loads(qp.read_text(encoding="utf-8"))
        else:
            _quiz = {"quiz": [], "riddles": {}}


@app.get("/api/wiki")
def wiki_all():
    _load_content()
    return {
        "categories": {k: v for k, v in _wiki.items() if k != "其他"},
        "other": _wiki.get("其他", []),
        "stats": {k: len(v) for k, v in _wiki.items()},
    }


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
    n = min(max(req.n, 1), 20)
    picked = _rnd.sample(pool, min(n, len(pool)))
    for i, p in enumerate(picked):
        p = dict(p)
        p["id"] = f"q{_rnd.randint(100000, 999999)}"
        picked[i] = p
    return {"questions": picked}


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
