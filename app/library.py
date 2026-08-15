# -*- coding: utf-8 -*-
"""阅读库：原版小说目录/章节全文、插图版PDF、人祖传、资料合集HTML。"""
import html
import os
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
NOVEL_ROOT = BASE.parent / "gu-zhen-ren"
PDF_ROOT = BASE.parent / "gu_zhen_ren_pdf"
LORE_DOCX = BASE.parent / "gu-zhenren-lore" / "蛊真人资料合集.docx"


_CN = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_vol_num(s: str):
    """提取 第N卷/章/节 的汉字数字并转整数（支持 一~九、十、几十、几十几）。"""
    m = re.search(r"第([一二三四五六七八九十]+)(?:卷|章|节)", s)
    if not m:
        return 0
    txt = m.group(1)
    if "十" not in txt:
        return _CN.get(txt, 0)
    a, _, b = txt.partition("十")
    return (_CN.get(a, 1) if a else 1) * 10 + _CN.get(b, 0)


def _natural_key(s: str):
    # 汉字数字卷/章序优先（“第二卷” < “第三卷”），其余按数字/字符兜底
    return (_cn_vol_num(s), [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)])


def _first_title(lines):
    for ln in lines:
        if ln.strip() and not re.fullmatch(r"[=\-—\s·]+", ln.strip()):
            return ln.strip()
    return lines[0].strip() if lines else ""


def novel_volumes():
    """返回 [{name, chapters: [{n, title, file}]}]"""
    vols = []
    if not NOVEL_ROOT.is_dir():
        return vols
    for vdir in sorted(os.listdir(NOVEL_ROOT), key=_natural_key):
        vpath = NOVEL_ROOT / vdir
        if not vpath.is_dir():
            continue
        chapters = []
        for fn in sorted(os.listdir(vpath), key=_natural_key):
            if not fn.endswith(".txt"):
                continue
            m = re.search(r"第(\d+)章", fn)
            n = int(m.group(1)) if m else 0
            try:
                with open(vpath / fn, encoding="utf-8", errors="replace") as f:
                    lines = [l.strip() for l in f.read().splitlines() if l.strip()]
            except OSError:
                lines = []
            chapters.append({"n": n, "title": _first_title(lines), "file": fn})
        if chapters:
            vols.append({"name": vdir, "chapters": chapters})
    return vols


def chapter_text(vol: str, chapter: int):
    """返回 {vol, chapter, title, text, path} 或 None"""
    vdir = NOVEL_ROOT / vol
    if not vdir.is_dir():
        return None
    if chapter == 0:
        cand = vdir / "序.txt"
        fname = "序.txt"
    else:
        fname = f"第{chapter}章.txt"
        cand = vdir / fname
    if not cand.is_file():
        # 容错：按文件名匹配 第N章
        for fn in os.listdir(vdir):
            m = re.search(rf"第{chapter}章", fn)
            if m:
                cand = vdir / fn
                fname = fn
                break
        else:
            return None
    try:
        with open(cand, encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except OSError:
        return None
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        return None
    return {
        "vol": vol, "chapter": chapter, "file": fname,
        "title": _first_title(lines),
        "text": "\n".join(lines[1:]),
        "path": str(cand),
    }


def pdf_files():
    """返回 [{group, name, path, url}]"""
    out = []
    if not PDF_ROOT.is_dir():
        return out
    groups = {"蛊真人": "插图版", "人祖传": "人祖传"}
    for gdir in sorted(os.listdir(PDF_ROOT), key=_natural_key):
        gp = PDF_ROOT / gdir
        if not gp.is_dir():
            continue
        for fn in sorted(os.listdir(gp), key=_natural_key):
            if fn.lower().endswith(".pdf"):
                rel = f"{gdir}/{fn}"
                out.append({
                    "group": groups.get(gdir, gdir),
                    "name": fn,
                    "url": f"/files/{rel}",
                    "path": str(gp / fn),
                })
    return out


_lore_html_cache = None


def lore_html():
    """资料合集 docx -> HTML（带目录锚点），进程内缓存。"""
    global _lore_html_cache
    if _lore_html_cache is not None:
        return _lore_html_cache
    from docx import Document
    doc = Document(str(LORE_DOCX))
    raw = [(p.text.strip(), (p.style.name if p.style else "") or "")
           for p in doc.paragraphs if p.text and p.text.strip()]
    paras = [(t, s) for t, s in raw if not re.fullmatch(r"\[\d+\]\s*", t)]

    # 合并残段：以【/】开头的行是上一条目的尾注残段，拼回前一行
    merged = []
    for t, s in paras:
        if (t.startswith("【") or t.startswith("】")) and merged:
            merged[-1] = (merged[-1][0] + t, merged[-1][1])
        else:
            merged.append((t, s))

    # 一级大节名（docx 无样式层级，用内容启发式分级）
    L1_KEYWORDS = ("蛊虫百科", "百科内容", "作品简介", "作品目录", "作品设定", "背景设定",
                   "世界观", "修行体系", "流派", "人物图鉴", "势力分布", "仙蛊屋全集", "仙蛊屋",
                   "灾劫资料", "杀招体系", "荒兽", "人祖传", "尊者", "语录", "金句", "访谈",
                   "资料统计", "蛊仙数据", "奇蛊榜", "仙蛊榜", "魔蛊榜", "境界", "蛊师相关")

    def looks_like_body(t):
        """内容像正文（编号行/长句/句末标点）的行，即使带标题样式也不算标题。"""
        if re.match(r"^\d+[\.、]\s*", t):
            return True
        if len(t) > 30:
            return True
        if t.endswith(("。", "，", "！", "？", "；", "、", "：", ":")):
            return True
        return False

    def heading_level(t, style):
        """返回 1/2/None（None=非标题）。样式优先，内容校验兜底。"""
        if style:
            if "Heading 1" in style or "标题 1" in style:
                return None if looks_like_body(t) else 1
            if "Heading" in style or "标题" in style:
                return None if looks_like_body(t) else 2
        if looks_like_body(t):
            return None
        if len(t) < 2 or len(t) > 24:
            return None
        if t.startswith(("【", "[", "（", "(")):
            return None
        if re.fullmatch(r"[\]\]）\)\-—=·\s]+", t):
            return None
        if "：" in t or ":" in t:
            return None
        if any(k in t for k in L1_KEYWORDS) and len(t) <= 14:
            return 1
        return 2

    # 优先使用 AI 审核的目录（scripts/ai_toc.py 生成）
    import json as _json
    from app.config import DATA_DIR as _DD
    toc_items = None
    _toc_path = _DD / "lore_toc.json"
    if _toc_path.is_file():
        try:
            toc_items = _json.loads(_toc_path.read_text(encoding="utf-8"))["items"]
        except Exception:
            toc_items = None

    parts = ["<h1>《蛊真人》资料合集</h1>"]
    toc = []
    idx = 0
    seen_toc = set()
    toc_stack = []  # (level, 是否已生成该级 summary)
    for pi, (p, style) in enumerate(merged):
        lv = None
        txt = p
        if toc_items is not None and pi < len(toc_items):
            lv = int(toc_items[pi].get("level", 0))
            txt = str(toc_items[pi].get("text") or p)
        else:
            lv = heading_level(p, style)
        e = html.escape(txt)
        if lv:
            idx += 1
            anchor = f"sec{idx}"
            cls = f"l{min(lv, 3)}"
            parts.append(f'<h2 class="{cls}" id="{anchor}">{e}</h2>')
            if e in seen_toc:
                continue
            seen_toc.add(e)
            # 关闭比当前级别深的 open details
            while toc_stack and toc_stack[-1] >= lv:
                toc_stack.pop()
                toc.append("</details>")
            if lv == 3:
                toc.append(f'<a class="toc-l3" href="#{anchor}">{e}</a>')
            else:
                toc.append(f'<details open class="toc-grp"><summary><a href="#{anchor}">{e}</a></summary>')
                toc_stack.append(lv)
        else:
            parts.append(f"<p>{e}</p>")
    while toc_stack:
        toc_stack.pop()
        toc.append("</details>")
    _lore_html_cache = (
        "<style>body{font-family:'PingFang SC','Microsoft YaHei',sans-serif;line-height:1.9;margin:0;background:#f5f3ee}"
        "#toc{position:fixed;left:0;top:0;bottom:0;width:240px;overflow-y:auto;background:#fffdf7;border-right:1px solid #e5e0d6;padding:14px 10px;font-size:12px;z-index:5}"
        "#toc h3{font-size:13px;margin:0 0 8px 6px;color:#7a5c3e;cursor:pointer;user-select:none}"
        "#toc a{display:block;color:#7a5c3e;text-decoration:none;margin:2px 0;line-height:1.6;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        "#toc a:hover{background:#f0e9da;border-radius:4px}"
        "#toc summary{list-style:none;cursor:pointer;font-weight:700;color:#5a4530;margin-top:6px;user-select:none}"
        "#toc summary::-webkit-details-marker{display:none}"
        "#toc summary::before{content:'▾ ';color:#b08d57}"
        "#toc details:not([open])>summary::before{content:'▸ '}"
        "#toc summary a{display:inline;margin:0;font-weight:700}"
        "#toc .toc-grp2 summary{font-weight:600;color:#7a5c3e;margin-top:2px;padding-left:10px}"
        "#toc .toc-grp2 summary::before{content:'▾ '}"
        "#toc .toc-grp2 a{font-weight:400;display:inline}"
        "#toc .toc-grp{padding-left:2px}"
        "#toc .toc-grp2{padding-left:10px}"
        "#toc .toc-l3{padding-left:24px;color:#9a9284;font-size:11px}"
        "#content{margin-left:260px;max-width:860px;padding:24px 32px 60px;background:#fff;min-height:100vh}"
        "#toc .toc-top{display:flex;justify-content:space-between;align-items:center;font-size:13px;color:#7a5c3e;margin:0 2px 8px}"
        "#toc .toc-top button{border:1px solid #e5e0d6;background:#fff;border-radius:6px;padding:1px 10px;cursor:pointer;font-size:12px}"
        "#toc-show{position:sticky;top:0;z-index:9;border:1px solid #e5e0d6;background:#fffdf7;border-radius:8px;padding:5px 14px;font-size:13px;cursor:pointer;color:#7a5c3e;margin-bottom:10px}"
        "body.toc-hidden #toc{width:28px;padding:10px 3px}"
        "body.toc-hidden #tocbody{display:none}"
        "body.toc-hidden #toc .toc-title{display:none}"
        "body.toc-hidden #toc .toc-top{justify-content:center}"
        "body.toc-hidden #toc .toc-top button{transform:rotate(180deg)}"
        "body.toc-hidden #content{margin-left:36px}"
        "h1{font-size:22px}h2.l1{font-size:18px;margin-top:32px;border-left:4px solid #7a5c3e;padding-left:10px}"
        "h2.l2{font-size:15px;margin-top:22px;color:#5a4530;border-left:3px solid #b08d57;padding-left:8px}"
        "h2.l3{font-size:14px;margin-top:16px;color:#7a5c3e;padding-left:6px}"
        "p{margin:8px 0;color:#333}</style>"
        '<div id="toc"><div class="toc-top"><span class="toc-title">📑 目录</span><button onclick="toggleTocSide()" title="收起/展开目录">«</button></div><div id="tocbody">' + "".join(toc) + "</div></div>"
        + '<div id="content">' + "".join(parts) + "</div>"
        + "<script>function toggleTocSide(){document.body.classList.toggle('toc-hidden');}</script>"
    )
    return _lore_html_cache
