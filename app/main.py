# -*- coding: utf-8 -*-
"""《蛊真人》RAG 本地网页服务。
启动：uvicorn app.main:app --port 8000
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import config
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


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/health")
def health():
    if retriever is None:
        return {"ok": False, "error": "not loaded"}
    return {
        "ok": True,
        "has_key": bool(config.KEY),
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
        answer = ask_llm(system, user, config.KEY, config.BASE_URL, config.MODEL)
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
