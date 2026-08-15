# -*- coding: utf-8 -*-
"""从 wiki.json 自动生成题库 -> data/quiz.json（选择题 + 猜谜池，无需 LLM，零成本）
用法：python scripts/build_quiz.py
"""
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import DATA_DIR  # noqa: E402

TYPE_RE = re.compile(r"([\u4e00-\u9fa5]{1,4}类)蛊虫")


def main():
    wiki = json.load(open(os.path.join(str(DATA_DIR), "wiki.json"), encoding="utf-8"))
    random.seed(20260815)

    quiz = []
    # ---- 蛊虫选择题：描述 → 蛊名 ----
    gu = wiki.get("蛊虫", [])
    gnames = [e["name"] for e in gu]
    for e in gu:
        d = e["desc"]
        if len(d) < 15:
            continue
        dist = random.sample([n for n in gnames if n != e["name"]], 3)
        opts = [e["name"]] + dist
        random.shuffle(opts)
        quiz.append({
            "type": "蛊虫",
            "q": f"以下哪个蛊虫符合这段描述：{d[:40]}……",
            "options": opts, "answer": opts.index(e["name"]),
            "explain": f"{e['name']}：{d[:90]}",
        })
        if len([x for x in quiz if x["type"] == "蛊虫"]) >= 220:
            break

    # ---- 人物选择题：描述 → 人物 ----
    ppl = wiki.get("人物", [])
    pnames = [e["name"] for e in ppl]
    for e in ppl:
        d = e["desc"]
        if len(d) < 15:
            continue
        dist = random.sample([n for n in pnames if n != e["name"]], 3)
        opts = [e["name"]] + dist
        random.shuffle(opts)
        quiz.append({
            "type": "人物",
            "q": f"根据描述猜人物：{d[:40]}……",
            "options": opts, "answer": opts.index(e["name"]),
            "explain": f"{e['name']}：{d[:90]}",
        })
        if len([x for x in quiz if x["type"] == "人物"]) >= 120:
            break

    # ---- 蛊虫类型题：蛊名 → 类型 ----
    typed = []
    for e in gu:
        m = TYPE_RE.search(e["desc"])
        if m and len(m.group(1)) >= 2:
            typed.append((e["name"], m.group(1), e["desc"]))
    all_types = sorted({t for _, t, _ in typed})
    for name, t, d in typed:
        if len(all_types) < 4:
            break
        dist = random.sample([x for x in all_types if x != t], 3)
        opts = [t] + dist
        random.shuffle(opts)
        quiz.append({
            "type": "蛊虫类型",
            "q": f"「{name}」是什么类型的蛊虫？",
            "options": opts, "answer": opts.index(t),
            "explain": f"{name}：{d[:90]}",
        })
        if len([x for x in quiz if x["type"] == "蛊虫类型"]) >= 100:
            break

    # ---- 猜谜池 ----
    def rank_hint(e):
        """从原文可见的信息提炼第一句提示：转数 / 仙蛊 / 仙蛊屋 / 杀招 / 灾劫 / 势力 / 秘境。"""
        sub = e.get("sub", "") or ""
        d = e.get("desc", "") or ""
        sec = e.get("section", "") or ""
        m = re.search(r"([一二三四五六七八九十]+)转", sub)
        if m:
            return f"它是{m.group(1)}转蛊虫"
        if sub == "仙蛊":
            return "它是一只仙蛊"
        if "仙蛊屋" in sec or "蛊屋" in d:
            return "它是一座仙蛊屋"
        if "杀招" in sec or "杀招" in d[:20]:
            return "它是一种杀招"
        if "灾劫" in sec:
            return "它是一种灾劫"
        if "势力" in sec or "家族" in d or "天庭" in sec:
            return "它是一个势力或组织"
        if "天地秘境" in sec or "洞天" in d:
            return "它是一处天地秘境"
        if "境界" in sec or "流派" in sec:
            return "它是一种修行境界或流派"
        if "人祖" in sec:
            return "它出自人祖传的寓言故事"
        return None

    def riddle_pool(items, kind, limit=400):
        pool = []
        names = [e["name"] for e in items if len(e.get("desc", "")) >= 15]
        for e in items:
            d = e["desc"]
            if len(d) < 15:
                continue
            if kind == "gu":
                h = rank_hint(e)
                first = h if h else "它是《蛊真人》中的一种蛊虫"
            elif kind == "person":
                first = []
                if "尊者" in d:
                    first.append("它在书中是尊者级人物")
                elif "蛊仙" in d:
                    first.append("它是蛊仙")
                if "魔道" in d:
                    first.append("它出身魔道阵营")
                elif "正道" in d:
                    first.append("它出身正道阵营")
                first = first[0] if first else "它是《蛊真人》中的人物"
            else:
                h = rank_hint(e)
                first = h if h else "它是《蛊真人》中的一个重要事物"
            dist = random.sample([n for n in names if n != e["name"]], 3)
            opts = [e["name"]] + dist
            random.shuffle(opts)
            pool.append({
                "name": e["name"],
                "options": opts,
                "hints": [
                    first,
                    f"线索：{d[:40]}……",
                    f"它的名字共 {len(e['name'])} 个字，首字是「{e['name'][0]}」",
                ],
            })
            if len(pool) >= limit:
                break
        return pool

    item_src = (
        wiki.get("仙蛊屋", []) + wiki.get("灾劫", []) + wiki.get("杀招", [])
        + wiki.get("势力", []) + wiki.get("天地秘境", []) + wiki.get("五域地理", [])
        + wiki.get("世界设定", [])
    )
    riddles = {
        "gu": riddle_pool(gu, "gu"),
        "person": riddle_pool(ppl, "person"),
        "item": riddle_pool(item_src, "item"),
    }

    out = {"quiz": quiz, "riddles": riddles}
    with open(os.path.join(str(DATA_DIR), "quiz.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"quiz: {len(quiz)} 题  (蛊虫 {sum(1 for x in quiz if x['type']=='蛊虫')} / 人物 {sum(1 for x in quiz if x['type']=='人物')} / 类型 {sum(1 for x in quiz if x['type']=='蛊虫类型')})")
    print("riddles:", {k: len(v) for k, v in riddles.items()})
    for x in quiz[:3]:
        print("  例:", x["q"], "|", x["options"], "->", x["options"][x["answer"]])


if __name__ == "__main__":
    main()
