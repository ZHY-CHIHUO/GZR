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


@app.post("/api/ask")
def ask(req: AskReq):
    q = (req.question or "").strip()
    if not q:
        return JSONResponse({"error": "问题不能为空"}, status_code=400)
    if retriever is None:
        return JSONResponse({"error": "检索库未加载"}, status_code=503)
    # 一次检索（普通 + 词条名强制召回 + 词条名原文补充）合并完成
    hits = _force_wiki_hits(q, retriever.search(q, scope=req.scope))
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
    return {
        "answer": answer,
        "sources": shown_sources,
        "cost_rmb": estimate_cost(system, user, answer) if not mock else 0.0,
        "mock": mock,
        "web": web_used,
        "wiki_cites": _wiki_cites_in(answer) if (combined or not web_used and not gen_knowledge) else [],
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
