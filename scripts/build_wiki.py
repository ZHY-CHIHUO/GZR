# -*- coding: utf-8 -*-
"""从设定库(lore/meta.json)结构化提取百科条目 -> data/wiki.json
用法：python scripts/build_wiki.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import DATA_DIR  # noqa: E402

CATEGORY_RULES = [
    # 资料合集的主框架：这些分类优先于泛化的“蛊虫/人物”词命中。
    ("作品资料", ["作品简介", "作品目录", "作品设定", "背景介绍", "基本介绍"]),
    ("世界设定", ["世界观", "世界背景", "生灵蛊虫异人", "异人介绍"]),
    ("天地秘境", ["天地秘境", "人造天地秘境", "洞天秘境"]),
    ("五域地理", ["五域资料", "五域优劣", "五域特色", "五域时间", "西漠", "南疆", "北原", "中洲", "东海"]),
    ("人祖传", ["人祖传", "《人祖传》", "人祖及十子"]),
    ("人物", ["人物", "尊者", "蛊仙", "护道", "图鉴"]),
    ("蛊虫", ["蛊"]),
    ("势力", ["势力", "家族", "天庭", "长生天", "超级势力", "影宗", "联盟", "古派"]),
    ("仙蛊屋", ["仙蛊屋", "No."]),
    ("灾劫", ["灾劫"]),
    ("杀招", ["杀招"]),
    ("境界流派", ["境界", "流派", "修为", "真元", "仙元", "空窍"]),
    ("其他", []),
]

BAD_PREFIX = ("人物经历", "人物简介", "人物介绍", "个人形象", "人物形象", "来历", "经历", "简介", "介绍", "目录", "本章", "备注")

BAD_NAMES = {"它是", "这是", "那是", "他是", "她是", "可以", "因为", "所以", "但是", "如果", "其中", "所谓", "此外", "后来", "如今", "这时", "这时", "只见", "然而", "因此", "不过", "而且", "或者", "那么", "就是", "不是", "没有", "一位", "一只", "一个", "一些", "一次"}


def categorize(section):
    for cat, kws in CATEGORY_RULES:
        if any(k in section for k in kws):
            return cat
    return "其他"


def main():
    meta_path = os.path.join(str(DATA_DIR), "lore", "meta.json")
    chunks = json.load(open(meta_path, encoding="utf-8"))
    entries = {}
    seen = set()
    for ch in chunks:
        section = ch.get("section", "")
        cat = categorize(section)
        for line in ch["text"].splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^(.{1,14})[：:](.*)$", line)
            if not m:
                continue
            name, desc = m.group(1).strip(), m.group(2).strip()
            name = re.sub(r"^\d+[\.、]\s*", "", name)  # 去掉 "8.xxx" 编号前缀
            if len(name) < 2 or not desc:
                continue
            if name in BAD_NAMES or name.startswith(BAD_PREFIX):
                continue
            if re.search(r"[。！？；，、\s]", name):
                continue
            if re.match(r"^第[一二三四五六七八九十百\d]+[节章回卷]", name):
                continue
            if desc.count("、") > 6 or desc.count("，") > 12:
                continue  # 名单/列表行，非条目
            # 条目级二次分类：仙蛊屋 / 蛊虫转数细分
            sub = ""
            if "仙蛊屋" in desc or "蛊屋" in desc or "仙蛊屋" in name:
                cat = "仙蛊屋"
            elif "仙蛊" in desc:
                sub = "仙蛊"
            elif re.search(r"([一二三四五六七八九十]+)转", desc):
                m3 = re.search(r"([一二三四五六七八九十]+)转", desc)
                sub = m3.group(1) + "转"
            else:
                m4 = re.search(r"蛊([一二三四五六七八九十]+)转", section)
                sub = (m4.group(1) + "转") if m4 else "其他"
            key = (cat, name)
            if key in seen:
                entries[cat][name]["desc"] += " " + desc
                continue
            seen.add(key)
            entries.setdefault(cat, {})[name] = {"name": name, "desc": desc, "section": section, "sub": sub}
    out = {cat: sorted(v.values(), key=lambda e: len(e["desc"]), reverse=True) for cat, v in entries.items()}
    stats = {cat: len(v) for cat, v in out.items()}
    with open(os.path.join(str(DATA_DIR), "wiki.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("stats:", stats)
    for cat in ("蛊虫", "人物", "势力", "仙蛊屋"):
        if cat in out:
            print(f"\n{cat} 示例：")
            for e in out[cat][:4]:
                print("  -", e["name"], "|", e["desc"][:40])


if __name__ == "__main__":
    main()
