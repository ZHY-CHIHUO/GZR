# -*- coding: utf-8 -*-
"""《蛊真人》RAG 本地网页服务。
启动：uvicorn app.main:app --port 8000
"""
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global retriever
    retriever = Retriever(config.DATA_DIR, config.MODEL_CACHE, top_k=config.TOP_K)
    yield


app = FastAPI(title="蛊真人 RAG", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class AskReq(BaseModel):
    question: str


class SettingsReq(BaseModel):
    api_key: str | None = None
    model: str | None = None


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
    return FileResponse(target, filename=target.name)


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
    }


@app.post("/api/ask")
def ask(req: AskReq):
    q = (req.question or "").strip()
    if not q:
        return JSONResponse({"error": "问题不能为空"}, status_code=400)
    if retriever is None:
        return JSONResponse({"error": "检索库未加载"}, status_code=503)
    hits = retriever.search(q)
    system, user = build_prompt(q, hits, config.EXCERPT_CHARS)
    if config.KEY:
        try:
            answer = ask_llm(system, user, config.KEY, config.BASE_URL, config.MODEL)
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
    return {"ok": True, "has_key": bool(config.KEY), "model": config.MODEL}


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


# ---------- 阅读库 ----------

@app.get("/api/library")
def get_library():
    return {
        "volumes": library.novel_volumes(),
        "pdfs": library.pdf_files(),
        "lore": {
            "name": LORE_NAME,
            "html_url": "/api/lore/html",
            "download_url": "/api/lore/download",
        },
        "novel_root": str(library.NOVEL_ROOT),
    }


LORE_NAME = library.LORE_DOCX.name


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


@app.get("/api/lore/html")
def lore_html():
    return HTMLResponse(library.lore_html())


@app.get("/api/lore/download")
def lore_download():
    if not library.LORE_DOCX.is_file():
        raise HTTPException(404, "资料合集不存在")
    return FileResponse(library.LORE_DOCX, filename=library.LORE_DOCX.name)
