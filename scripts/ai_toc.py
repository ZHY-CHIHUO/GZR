# -*- coding: utf-8 -*-
"""AI 审核资料合集目录层级：对候选标题逐条分级（0=非标题, 1=一级, 2=二级, 3=三级）+ 修正文本。
输出 {DATA_DIR}/lore_toc.json：按文档顺序的 {text, level} 列表。
用法：python scripts/ai_toc.py
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import KEY, BASE_URL, MODEL, DATA_DIR  # noqa: E402

BATCH = 350

L1_KEYWORDS = ("蛊虫百科", "百科内容", "作品简介", "作品目录", "作品设定", "背景设定",
               "世界观", "修行体系", "流派", "人物图鉴", "势力分布", "仙蛊屋全集", "仙蛊屋",
               "灾劫资料", "杀招体系", "荒兽", "人祖传", "尊者", "语录", "金句", "访谈",
               "资料统计", "蛊仙数据", "奇蛊榜", "仙蛊榜", "魔蛊榜", "境界", "蛊师相关")


def looks_like_body(t):
    if re.match(r"^\d+[.、]\s*", t):
        return True
    if len(t) > 30:
        return True
    if t.endswith(("。", "，", "！", "？", "；", "、", "：", ":")):
        return True
    return False


def old_level(t, style):
    if style and ("Heading 1" in style or "标题 1" in style):
        return None if looks_like_body(t) else 1
    if style and ("Heading" in style or "标题" in style):
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


def extract_candidates():
    from docx import Document
    from app.library import LORE_DOCX
    doc = Document(str(LORE_DOCX))
    raw = [(p.text.strip(), (p.style.name if p.style else "") or "")
           for p in doc.paragraphs if p.text and p.text.strip()]
    paras = [(t, s) for t, s in raw if not re.fullmatch(r"\[\d+\]\s*", t)]
    merged = []
    for t, s in paras:
        if (t.startswith("【") or t.startswith("】")) and merged:
            merged[-1] = (merged[-1][0] + t, merged[-1][1])
        else:
            merged.append((t, s))
    cands = []
    for i, (t, s) in enumerate(merged):
        lv = old_level(t, s)
        if lv:
            cands.append((i, t, lv))
    return merged, cands


SYSTEM = (
    "你是《蛊真人》设定文档的结构审核专家。我给你一个从文档中提取的疑似标题列表，"
    "每个条目格式为：序号. 标题文本。请判断每一条："
    "1) 它是不是真正的章节/小节标题（书友名单、运营人员名单、正文句子、残段等不是标题，输出 level 0）；"
    "2) 若是标题，级别：1=一级大节（如 蛊虫百科、作品设定、人物图鉴），2=二级小节（如 蛊一转蛊虫、修为境界），3=三级小节；"
    "3) 修正标题文本：去掉编号前缀（如 1010.、第六章、3、No.17 等）和多余符号，只保留标题本身。"
    "层级参考：蛊虫百科 > 蛊一转蛊虫；人物图鉴 > 十尊者 > 元始仙尊；作品设定 > 背景设定 > 世界背景。"
    "注意：上古战阵应属于杀招/战阵类大节；大爱仙尊/炼天魔尊、黑天群月等若是人物条目请归入人物类或置 0；"
    "微信公众号蛊真人的运营员、书友名单等不是标题，输出 0。"
    "只输出一个 JSON 对象，键为原序号（字符串），值为 {\"level\": 0|1|2|3, \"text\": \"修正后标题\"}。"
    "不要输出 JSON 以外的任何文字，不要用 markdown 代码块。"
)


def parse_verdicts(text):
    text = re.sub(r"^\x60\x60\x60(?:json)?\s*|\s*\x60\x60\x60$", "", text.strip())
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    out = {}
    pat = re.compile(r'"(\d+)"\s*:\s*\{[^{}]*?"level"\s*:\s*(\d)[^{}]*?"text"\s*:\s*"((?:[^"\\]|\\.)*)"')
    for m2 in pat.finditer(text):
        out[m2.group(1)] = {"level": int(m2.group(2)), "text": m2.group(3).replace('\\"', '"')}
    if not out:
        pat2 = re.compile(r'"(\d+)"\s*:\s*\{[^{}]*?"text"\s*:\s*"((?:[^"\\]|\\.)*)"[^{}]*?"level"\s*:\s*(\d)')
        for m2 in pat2.finditer(text):
            out[m2.group(1)] = {"level": int(m2.group(3)), "text": m2.group(2).replace('\\"', '"')}
    return out


def ask_batch(items, batch_no):
    from openai import OpenAI
    client = OpenAI(api_key=KEY, base_url=BASE_URL)
    lines = [f"{i}. {t}" for i, t, _ in items]
    user = "疑似标题列表：\n" + "\n".join(lines) + "\n\n请输出JSON审核结果。"
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        temperature=0.1, max_tokens=4000,
    )
    return parse_verdicts(resp.choices[0].message.content or "")


def main():
    if not KEY:
        print("需要 DEEPSEEK_API_KEY")
        sys.exit(1)
    merged, cands = extract_candidates()
    print(f"候选标题: {len(cands)} 条")
    verdicts = {}
    for b in range(0, len(cands), BATCH):
        chunk = cands[b:b + BATCH]
        v = {}
        for attempt in range(3):
            try:
                v = ask_batch(chunk, b // BATCH + 1)
                if v:
                    break
            except Exception as e:
                print(f"批 {b // BATCH + 1} 第{attempt+1}次失败: {str(e)[:80]}")
                time.sleep(2)
        if not v:
            print(f"批 {b // BATCH + 1} 用旧规则兜底")
            v = {str(i): {"level": lv, "text": t} for i, t, lv in chunk}
        verdicts.update(v)
        print(f"批 {b // BATCH + 1} 完成，得到 {len(v)} 条判定")

    items = []
    cand_idx = {c[0] for c in cands}
    for i, (t, s) in enumerate(merged):
        if i in cand_idx:
            v = verdicts.get(str(i), {})
            lv = int(v.get("level", 2))
            txt = str(v.get("text") or t).strip()
            items.append({"text": txt or t, "level": lv})
        else:
            items.append({"text": t, "level": 0})
    with open(os.path.join(str(DATA_DIR), "lore_toc.json"), "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, ensure_ascii=False, indent=1)
    from collections import Counter
    print("lore_toc.json 已生成:", dict(Counter(it["level"] for it in items)),
          "->", os.path.join(str(DATA_DIR), "lore_toc.json"))


if __name__ == "__main__":
    main()
