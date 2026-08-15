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
from fastapi.staticfiles import StaticFiles
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
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


class AskReq(BaseModel):
    question: str
    scope: str = "all"          # all / novel / lore
    history: list = []          # [{role, content}, ...]


class SettingsReq(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    embed_model: str | None = None   # small / m3 / jina


class TestReq(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


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
        "categories": {k: v for k, v in _wiki.items() if k != "其他"},
        "other": _wiki.get("其他", []),
        "stats": {k: len(v) for k, v in _wiki.items()},
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
        return JSONResponse({"ok": False, "error": f"条目不存在：{cat} / {name}"}, status_code=404)
    if req.delete:
        entries.pop(idx)
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
