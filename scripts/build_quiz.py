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
    gu = wiki.get("蛊虫", [])
    ppl = wiki.get("人物", [])

    def excerpt(d, n):
        t = re.sub(r"\s+", " ", d).strip()
        if len(t) <= n:
            return t + ("……" if len(t) < len(d) else "")
        head = t[:n]
        cut = max(head.rfind(c) for c in "。！？；，、")
        if cut > n * 0.4:
            head = head[:cut + 1]
        return head + "……"

    RANKS = ["一转", "二转", "三转", "四转", "五转", "六转", "七转", "八转", "九转", "仙蛊"]

    def push(item):
        quiz.append(item)

    # ---- 蛊虫题 220：三种题型混排（描述→名称 / 名称→描述 / 转数）----
    gu_pool = [e for e in gu if len(e.get("desc", "")) >= 40]
    gu_ranked = [e for e in gu if re.search(r"([一二三四五六七八九十]+)转", e.get("sub", "") or "")]
    for e in gu_pool:
        if sum(1 for x in quiz if x["type"] == "蛊虫") >= 220:
            break
        d = e["desc"]
        kind = random.choice(["T1", "T1", "T2", "T3"])  # T1 偏多，打乱公式感
        if kind == "T3" and e.get("sub"):
            m = re.search(r"([一二三四五六七八九十]+)转", e["sub"])
            if m:
                ans = m.group(1) + "转"
                dist = random.sample([r for r in RANKS if r != ans], 3)
                opts = [ans] + dist
                random.shuffle(opts)
                push({"type": "蛊虫", "q": f"「{e['name']}」是几转蛊虫？",
                      "options": opts, "answer": opts.index(ans), "explain": f"{e['name']}：{d[:90]}"})
                continue
        if kind == "T2":
            others = [x for x in gu_pool if x is not e]
            if len(others) < 3:
                continue
            dist = [excerpt(x["desc"], 40) for x in random.sample(others, 3)]
            right = excerpt(d, 40)
            opts = [right] + dist
            random.shuffle(opts)
            push({"type": "蛊虫", "q": f"以下哪段描述对应蛊虫「{e['name']}」？",
                  "options": opts, "answer": opts.index(right), "explain": f"{e['name']}：{d[:90]}"})
            continue
        # T1：描述（更短）→ 名称
        others = [x for x in gu_pool if x is not e]
        if len(others) < 3:
            continue
        dist = [x["name"] for x in random.sample(others, 3)]
        opts = [e["name"]] + dist
        random.shuffle(opts)
        push({"type": "蛊虫", "q": f"以下哪个蛊虫符合这段描述：{excerpt(d, 26)}",
              "options": opts, "answer": opts.index(e["name"]), "explain": f"{e['name']}：{d[:90]}"})

    # ---- 人物题 120：描述→人物 / 描述匹配 / 阵营 ----
    ppl_pool = [e for e in ppl if len(e.get("desc", "")) >= 40]
    for e in ppl_pool:
        if sum(1 for x in quiz if x["type"] == "人物") >= 120:
            break
        d = e["desc"]
        kind = random.choice(["T1", "T1", "T2", "T3"])
        if kind == "T3":
            if "魔道" in d:
                ans = "魔道"
            elif "正道" in d:
                ans = "正道"
            else:
                ans = "散修/中立"
            dist = random.sample([x for x in ["正道", "魔道", "散修/中立", "异人"] if x != ans], 3)
            opts = [ans] + dist
            random.shuffle(opts)
            push({"type": "人物", "q": f"「{e['name']}」出身哪个阵营？",
                  "options": opts, "answer": opts.index(ans), "explain": f"{e['name']}：{d[:90]}"})
            continue
        if kind == "T2":
            others = [x for x in ppl_pool if x is not e]
            if len(others) < 3:
                continue
            dist = [excerpt(x["desc"], 42) for x in random.sample(others, 3)]
            right = excerpt(d, 42)
            opts = [right] + dist
            random.shuffle(opts)
            push({"type": "人物", "q": f"以下哪段描述对应人物「{e['name']}」？",
                  "options": opts, "answer": opts.index(right), "explain": f"{e['name']}：{d[:90]}"})
            continue
        others = [x for x in ppl_pool if x is not e]
        if len(others) < 3:
            continue
        dist = [x["name"] for x in random.sample(others, 3)]
        opts = [e["name"]] + dist
        random.shuffle(opts)
        push({"type": "人物", "q": f"以下哪位人物符合这段描述：{excerpt(d, 26)}",
              "options": opts, "answer": opts.index(e["name"]), "explain": f"{e['name']}：{d[:90]}"})

    # ---- 蛊虫类型题 100：蛊名 → 类型（措辞随机）----
    typed = []
    for e in gu:
        m = TYPE_RE.search(e["desc"])
        if m and len(m.group(1)) >= 2:
            typed.append((e["name"], m.group(1), e["desc"]))
    all_types = sorted({t for _, t, _ in typed})
    for name, t, d in typed:
        if sum(1 for x in quiz if x["type"] == "蛊虫类型") >= 100:
            break
        if len(all_types) < 4:
            break
        dist = random.sample([x for x in all_types if x != t], 3)
        opts = [t] + dist
        random.shuffle(opts)
        stem = random.choice([f"「{name}」是什么类型的蛊虫？", f"「{name}」属于哪一类蛊虫？"])
        push({"type": "蛊虫类型", "q": stem,
              "options": opts, "answer": opts.index(t), "explain": f"{name}：{d[:90]}"})

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
            hints = [first]
            clean = re.sub(r"\s+", " ", d).strip()
            # 最多切 3 段线索，按句读收尾，保证提示数量
            chunks = []
            t = clean
            while t and len(chunks) < 3:
                head = t[:44]
                cut = max(head.rfind(c) for c in "。！？；，、")
                if cut > 14:
                    head = head[:cut + 1]
                    t = t[cut + 1:].lstrip("。！？；，、 ")
                else:
                    t = t[44:]
                chunks.append(head.strip())
            for ch in chunks:
                hints.append("线索：" + (ch + "……" if len(ch) >= 40 else ch))
            roles = re.findall(r"【([^】]{2,30})】", d)
            rel = next((r for r in roles if not re.search(r"第[零一二三四五六七八九十百千]+节", r)), None)
            if rel:
                hints.append("相关角色：" + rel[:26])
            secm = next((r for r in roles if re.search(r"第[零一二三四五六七八九十百千]+节", r)), None)
            if secm:
                hints.append("出处：" + secm[:24])
            hints.append(f"它的名字共 {len(e['name'])} 个字，首字是「{e['name'][0]}」")
            # 保证至少 5 条
            while len(hints) < 5:
                hints.append("提示：它的设定收录于《蛊真人》资料库。")
            pool.append({
                "name": e["name"],
                "options": opts,
                "hints": hints[:8],
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
