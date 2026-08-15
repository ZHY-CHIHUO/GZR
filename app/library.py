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

    def is_heading(t, style):
        if style and ("Heading" in style or "标题" in style):
            return True
        if len(t) < 2 or len(t) > 24:
            return False
        if t.startswith(("【", "[", "（", "(")):
            return False
        if re.fullmatch(r"[\]\]）\)\-—=·\s]+", t):
            return False
        if "：" in t or ":" in t:
            return False
        if t.endswith(("。", "！", "？", "；", "，", "、")):
            return False
        return True

    parts = ["<h1>《蛊真人》资料合集</h1>"]
    toc = []
    idx = 0
    seen_toc = set()
    for p, style in merged:
        e = html.escape(p)
        if is_heading(p, style):
            idx += 1
            anchor = f"sec{idx}"
            if e not in seen_toc:
                seen_toc.add(e)
                toc.append(f'<a href="#{anchor}">{e}</a>')
            parts.append(f'<h2 id="{anchor}">{e}</h2>')
        else:
            parts.append(f"<p>{e}</p>")
    _lore_html_cache = (
        "<style>body{font-family:'PingFang SC','Microsoft YaHei',sans-serif;line-height:1.9;max-width:860px;margin:0 auto;padding:24px}"
        "h1{font-size:22px}h2{font-size:17px;margin-top:28px;border-left:4px solid #b08d57;padding-left:10px}"
        "p{margin:8px 0;color:#333}.toc{font-size:13px;columns:2;column-gap:32px;background:#faf7f0;padding:12px 16px;border-radius:8px}"
        ".toc a{display:block;color:#7a5c3e;text-decoration:none;margin:2px 0}</style>"
        '<div class="toc">' + "".join(toc) + "</div>" + "".join(parts)
    )
    return _lore_html_cache
