# -*- coding: utf-8 -*-
"""Build the curated wiki categories from the structured lore source.

The migration intentionally rebuilds the user-requested catalogue areas from
their authoritative source chapters.  It leaves unrelated manual corrections
in place, including the ranked 蛊虫 entries and the recycle-bin records.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
WIKI_PATH = BASE / "data_jina2" / "wiki.json"
LORE_TOC_PATH = BASE / "data_jina2" / "lore_toc.json"
LEAF_KEYS = {"intro", "desc", "sections", "aliases"}
CHAPTER_PREFIX = re.compile(r"^第[一二三四五六七八九十百千万零〇0-9]+章")
LABELED_LINE = re.compile(r"^([^：:\n]{1,32})[：:](.*)$")
CONTINUATION_LABELS = {
    "注",
    "补",
    "释",
    "一",
    "二",
    "三",
    "四",
    "五",
    "六",
    "七",
    "八",
    "九",
    "十",
}


def is_leaf(value):
    return isinstance(value, dict) and any(key in value for key in LEAF_KEYS)


def iter_leaves(node, path=()):
    if not isinstance(node, dict):
        return
    for name, value in node.items():
        if is_leaf(value):
            yield path, name, value
        elif isinstance(value, dict):
            yield from iter_leaves(value, path + (name,))


def count_leaves(data):
    return sum(
        1
        for category, node in data.items()
        if category != "_deleted" and isinstance(node, dict)
        for _path, _name, _entry in iter_leaves(node)
    )


def source_block(items, title):
    start = next(
        (
            index
            for index, item in enumerate(items)
            if item.get("level") == 1 and item.get("text") == title
        ),
        None,
    )
    if start is None:
        raise ValueError(f"资料源中找不到《{title}》")
    end = next(
        (
            index
            for index in range(start + 1, len(items))
            if items[index].get("level") == 1
        ),
        len(items),
    )
    return items[start + 1 : end]


def clean_chapter_name(title):
    return CHAPTER_PREFIX.sub("", str(title or "")).strip()


def source_chapters(items, title):
    chapters = []
    current_name = None
    current_items = []
    for item in source_block(items, title):
        if item.get("level") == 2:
            if current_name:
                chapters.append((current_name, current_items))
            current_name = clean_chapter_name(item.get("text", ""))
            current_items = []
        elif current_name:
            current_items.append(item)
    if current_name:
        chapters.append((current_name, current_items))
    if not chapters:
        raise ValueError(f"《{title}》没有可用章节")
    return chapters


def entry(desc, section, aliases=None):
    result = {"section": section, "desc": str(desc or "").strip()}
    if aliases:
        result["aliases"] = list(dict.fromkeys(aliases))
    return result


def append_text(target, text, label="补充资料"):
    text = str(text or "").strip()
    if not text:
        return
    current = str(target.get("desc") or "").strip()
    if text in current:
        return
    target["desc"] = f"{current}\n\n{label}：\n{text}".strip() if current else text


def split_labeled_entries(lines, fallback_name):
    """Split source paragraphs at concise ``名称：内容`` labels.

    Editorial markers such as ``注：`` and ``补：`` remain attached to the
    preceding entry.  This keeps the supplied qualifications with the entry
    they explain rather than turning them into meaningless standalone cards.
    """

    records = {}
    current = fallback_name
    records[current] = []
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line:
            continue
        matched = LABELED_LINE.match(line)
        if matched:
            label, remainder = (part.strip() for part in matched.groups())
            is_marker = (
                label in CONTINUATION_LABELS
                or label.startswith(("“", "‘", "「", "【"))
                or label.endswith(("注", "补"))
            )
            if label and not is_marker:
                current = label
                records.setdefault(current, [])
                if remainder:
                    records[current].append(remainder)
                continue
        records.setdefault(current, []).append(line)
    return [(name, "\n".join(parts).strip()) for name, parts in records.items() if parts]


REALM_CHAPTERS = (
    "界壁",
    "中州",
    "北原",
    "南疆",
    "西漠",
    "东海",
    "五域特色与文化活动",
    "五域优劣对比",
)

VENERABLE_NAMES = {
    "元始": "元始仙尊",
    "星宿": "星宿仙尊",
    "无极": "无极魔尊",
    "狂蛮": "狂蛮魔尊",
    "红莲": "红莲魔尊",
    "元莲": "元莲仙尊",
    "盗天": "盗天魔尊",
    "巨阳": "巨阳仙尊",
    "幽魂": "幽魂魔尊",
    "乐土": "乐土仙尊",
}

PERSON_NAME_ALIASES = {
    "古月方源": "方源",
    "狂蛮": "狂蛮魔尊",
    "元始": "元始仙尊",
    "星宿": "星宿仙尊",
    "无极": "无极魔尊",
    "红莲": "红莲魔尊",
    "元莲": "元莲仙尊",
    "盗天": "盗天魔尊",
    "巨阳": "巨阳仙尊",
    "幽魂": "幽魂魔尊",
    "乐土": "乐土仙尊",
    "魔尊幽魂": "幽魂魔尊",
    "禁师": "陶铸",
    "禁师·陶铸": "陶铸",
    "血龙·宋紫星": "宋紫星",
    "仙猴王·石磊": "石磊",
    "黑月仙子·黑楼兰": "黑楼兰",
    "剑仙·薄青": "薄青",
    "药皇·药三秋": "药皇",
    "烈魔仙·丹乔": "丹乔",
    "雷鬼真君·井斓": "雷鬼真君",
    "星宿仙僵·七星子": "七星子",
}

PERSON_ALIASES = {
    "元始仙尊": ["元始"],
    "星宿仙尊": ["星宿"],
    "无极魔尊": ["无极"],
    "狂蛮魔尊": ["狂蛮"],
    "红莲魔尊": ["红莲", "洪亭"],
    "元莲仙尊": ["元莲"],
    "盗天魔尊": ["盗天", "本杰孙", "Ben·Jason"],
    "巨阳仙尊": ["巨阳"],
    "幽魂魔尊": ["幽魂", "冥幽"],
    "乐土仙尊": ["乐土"],
}

LEGACY_NON_PEOPLE = {
    "五界大限阵",
    "陶铸真意",
    "人物成就",
    "个人经历",
    "注意",
    "五禁玄光气",
    "容貌",
    "流派",
    "传承",
    "境界",
    "修为",
    "本命蛊",
    "仙蛊",
    "代表杀招",
    "身份",
    "阵营",
    "人物",
    "称号",
    "大梦仙尊",
}

LEGACY_NON_PERSON_PATH_PARTS = {"人物资料", "测试树", "仙蛊"}
PERSON_RECORD = re.compile(r"^([^：:；;\n]{1,60})[：:；;]\s*(.+)$")

SCHOOL_ENTRIES = (
    (
        "流派",
        """“流派”即蛊师修行的倾向，不论蛊师还是蛊仙，甚至是动物植物，都会有一个流派的选择倾向，蛊师在升仙之时是哪个流派，升仙之后大多都会一直修行这个流派。兼修两个流派者，往往需有兼修法门，降低道痕互斥，否则会因道痕互斥实力降低。
“将己有的知识、资讯、蛊虫、杀招归纳整合到同一个流派内，形成一个完整的体系，即是开创流派。”一一古月阴荒（无限血核运营官）""",
    ),
    (
        "境界",
        """流派境界从低到高分为：无，普通，大师，宗师，大宗师，无上大宗师。
大师境界，能对流派产生直觉。
宗师境界，触类旁通，能以主修流派模拟其它流派威能。
大宗师境界，对道痕本身有深刻理解，可以随意拆卸使用杀招，可以直接利用自然界的道痕。吸收梦境/真意仅可达到准无上大宗师（吸收梦境可达上限曾为大宗师，后更改）。
无上大宗师境界，对道理法则的理解与天地齐平，不仅完全洞悉了流派的全部奥妙，而且还能推陈出新。并且能够创造出无需仙元的杀招。可以吸收元镜达到无上大宗师境界。
注：境界不代表成果，即便是无上在本流派内也有不清楚未掌握的成果。且一些成果含有多流派要素，需多流派境界达标方可掌握。""",
    ),
    (
        "道主",
        """所谓道主，便是一道之主。当蛊仙拥有无上大宗师境界，成为尊者。领袖一道，自身的进步便是流派的进步，便是天地的进步，那么他就是道主了。完整道主：炼化完蛊界的该道自然道痕的道主。
注：仙材、生物等不构成自然环境的道痕无需炼化便可成为完整道主，如需炼化亦可，而光阴长河/空穴则无法完全炼化。身为道主，蛊尊能够感知天地自然中自身统御流派的全部道痕，并且配合九转仙元加以炼化！炼化之后的道痕，蛊尊能够随意操纵。
注：道主指的是一道之主，主修流派无上大宗师境界+尊者，便是道主。道主并不是指宗师、大宗师这种境界划分。
蛊真人（作者）在群访谈时说过，尊者+无上大宗师境界=道主（此指方源，其他尊者仅可一道道主）。简单来说道主可以看做尊者。""",
    ),
    (
        "流派上限",
        """流派的上限并不是一成不变的。流派的上限可以通过蛊修努力提升。开创一种新的蛊虫，提升蛊虫的转数上限，研究一个新的板块等等都是在提升流派。
因此流派的提升进步与蛊修息息相关。往往此流派的蛊修、人才越多，提升越快。
注：并非只有某流派的无上大宗师/尊者/道主才能提升该流派的天地上限。普通蛊师蛊仙亦可缓慢提升天地上限。
例如人道、天道等修行门槛太高，很难普及，缺少蛊修去推动。
又如运道、画道等被开创者和后继者谨慎保存，流传范围十分有限，缺乏基础。有些流派例如气道、力道等在过去曾经兴盛，但相应的修行资源和蛊虫逐渐稀少，逐渐脱离主流。
而金道、土道、水道等修行资源易得、蛊虫易得、修行成本低、流传广泛、可参考借鉴的信息众多。又如练道，乃是蛊修的必修流派，虽可不精，但不可不会。""",
    ),
    (
        "各种流派",
        """现知流派：
太古时期人祖时代：宇、宙、人。
远古时代：气、奴、智、星、阵、炼、炎。
上古时代：律、变化、力、风、光、暗、食。
中古时代：木、画、偷、水、运、阴阳、金、冰、雪、云、土、雷、信、音。
近古时代：骨、虚、禁、魂。
近代：剑、丹。
现代：兵。
未来兴起的流派：梦。
未知时代的流派：血、毒、魅、幻、刀、情、影、月等。""",
    ),
    (
        "流派开创者",
        """人道：人祖。
气道、奴道：元始仙尊。
智道、星道：星宿仙尊。
律道：无极魔尊。
力道、变化道：狂蛮魔尊。
木道、画道：元莲仙尊。
偷道：盗天魔尊。
运道、阴阳道：巨阳仙尊。
魂道：幽魂魔尊。
血道：血海老祖（巨阳分身）。
剑道：薄青（幽魂分身）。
食道：龙鳄兽人蛊仙。
水道：水尼。
虚道：虚无邪。
丹道：青玉鹤-阮丹。
兵道：车尾。""",
    ),
)


def build_realms(items):
    realms = {}
    for chapter_name, chapter_items in source_chapters(items, "五域资料"):
        if chapter_name not in REALM_CHAPTERS:
            continue
        lines = [item.get("text", "") for item in chapter_items]
        chapter = {}
        for name, desc in split_labeled_entries(lines, chapter_name):
            chapter[name] = entry(desc, "五域资料")
        if not chapter:
            chapter[chapter_name] = entry("\n".join(lines), "五域资料")
        realms[chapter_name] = chapter
    return realms


def _add_aliases(target, aliases):
    existing = list(target.get("aliases") or [])
    for alias in aliases or []:
        alias = str(alias or "").strip()
        if alias and alias != target.get("name") and alias not in existing:
            existing.append(alias)
    if existing:
        target["aliases"] = existing


def canonical_person_name(name):
    normalized = str(name or "").strip()
    return PERSON_NAME_ALIASES.get(normalized, normalized)


def parse_person_record(text):
    matched = PERSON_RECORD.match(str(text or "").strip())
    if not matched:
        return None
    name, desc = (part.strip() for part in matched.groups())
    if not name or name in CONTINUATION_LABELS:
        return None
    return name, desc


def chapter_text(chapter_items):
    return "\n".join(
        str(item.get("text", "")).strip()
        for item in chapter_items
        if str(item.get("text", "")).strip()
    )


def is_legacy_person(path, name, raw_entry):
    if any(part in LEGACY_NON_PERSON_PATH_PARTS for part in path):
        return False
    if name in LEGACY_NON_PEOPLE:
        return False
    return bool(str(raw_entry.get("desc") or raw_entry.get("intro") or "").strip())


def build_people(items, legacy_people):
    """Build a single-level 人物 catalogue.

    The 蛊仙数据统计 block supplies the display order.  The two curated
    chapter sources then enrich those records in place, so detailed articles
    such as 元始仙尊 and 凤九歌 remain directly reachable by their names.
    """

    people = {}

    def put(name, desc, source, aliases=None):
        original_name = str(name or "").strip()
        canonical_name = canonical_person_name(original_name)
        desc = str(desc or "").strip()
        if not canonical_name or not desc:
            return None
        target = people.get(canonical_name)
        merged_aliases = list(aliases or [])
        if original_name != canonical_name:
            merged_aliases.append(original_name)
        if target is None:
            people[canonical_name] = entry(desc, "人物", merged_aliases)
            return people[canonical_name]
        append_text(target, desc, source)
        _add_aliases(target, merged_aliases)
        return target

    # 方源 is outside the 蛊仙数据统计 roster but is the first character in the
    # overall 人物 catalogue.  Preserve the existing article before inserting
    # the source-ordered 蛊仙 list.
    for path, name, raw_entry in iter_leaves(legacy_people):
        if canonical_person_name(name) != "方源" or not is_legacy_person(path, name, raw_entry):
            continue
        put(name, raw_entry.get("desc") or raw_entry.get("intro"), "旧版人物资料", raw_entry.get("aliases"))
        break

    for item in source_block(items, "蛊仙数据统计"):
        if item.get("level") != 0:
            continue
        record = parse_person_record(item.get("text", ""))
        if record:
            put(*record, "蛊仙数据统计")

    for chapter_name, chapter_items in source_chapters(items, "十尊者"):
        canonical_name = VENERABLE_NAMES.get(chapter_name)
        if canonical_name:
            put(canonical_name, chapter_text(chapter_items), "十尊者", PERSON_ALIASES.get(canonical_name))

    detailed_people = {
        "凤九歌",
        "武庸",
        "太白云生",
        "白凝冰",
        "龙公",
        "吴帅",
        "楚度",
        "黑楼兰",
        "古月方正",
        "陶铸",
    }
    for chapter_name, chapter_items in source_chapters(items, "人物篇"):
        if chapter_name in detailed_people:
            put(chapter_name, chapter_text(chapter_items), "人物篇")
            continue
        if chapter_name == "其他角色":
            for item in chapter_items:
                if item.get("level") != 0:
                    continue
                record = parse_person_record(item.get("text", ""))
                if record:
                    put(*record, "人物篇")
            continue
        if chapter_name == "兼修转修的蛊仙":
            for item in chapter_items:
                record = parse_person_record(item.get("text", ""))
                if record:
                    put(*record, "人物篇")

    for path, name, raw_entry in iter_leaves(legacy_people):
        if canonical_person_name(name) == "方源" or not is_legacy_person(path, name, raw_entry):
            continue
        canonical_name = canonical_person_name(name)
        existing = people.get(canonical_name)
        if existing is not None:
            # The new sources are authoritative for matching people.  Keep
            # aliases from the previous tree but avoid duplicating its prose.
            _add_aliases(existing, [name, *(raw_entry.get("aliases") or [])])
            continue
        put(name, raw_entry.get("desc") or raw_entry.get("intro"), "旧版人物资料", raw_entry.get("aliases"))

    for canonical_name, aliases in PERSON_ALIASES.items():
        target = people.get(canonical_name)
        if target is not None:
            _add_aliases(target, aliases)

    for canonical_name, target in people.items():
        aliases = [alias for alias in target.get("aliases", []) if alias != canonical_name]
        if aliases:
            target["aliases"] = aliases
        else:
            target.pop("aliases", None)

    return people


def build_aliens(items):
    aliens = {}
    for chapter_name, chapter_items in source_chapters(items, "异人"):
        desc = "\n".join(
            str(item.get("text", "")).strip()
            for item in chapter_items
            if str(item.get("text", "")).strip()
        )
        aliens[chapter_name] = entry(desc, "异人")
    return aliens


def build_school_settings():
    return {
        name: entry(desc, "流派设定")
        for name, desc in SCHOOL_ENTRIES
    }


def normalize_basic_settings(data):
    basic = data.get("基本设定")
    if not isinstance(basic, dict):
        raise ValueError("缺少基本设定分类")
    updated = 0
    for _path, _name, value in iter_leaves(basic):
        if value.get("section") != "基本设定":
            value["section"] = "基本设定"
            updated += 1
    return updated


def preserve_manual_adjustments(data):
    """Keep the explicitly requested manual data corrections stable."""

    gu = data.get("蛊虫")
    if not isinstance(gu, dict):
        raise ValueError("缺少蛊虫分类")
    eighth = gu.setdefault("八转", {})
    ninth = gu.get("九转", {})
    if not isinstance(eighth, dict) or not isinstance(ninth, dict):
        raise ValueError("蛊虫转数分组格式错误")
    if "宿命蛊" in ninth:
        # The requested correction is eight-rank placement.  Prefer a
        # pre-existing eight-rank version if a partial prior edit left both.
        eighth.setdefault("宿命蛊", ninth["宿命蛊"])
        ninth.pop("宿命蛊")

    other = gu.get("其他")
    if other is not None:
        if not isinstance(other, dict) or not all(is_leaf(value) for value in other.values()):
            raise ValueError("蛊虫 / 其他必须只包含直接词条")
        collisions = set(other).intersection(set(gu) - {"其他"})
        if collisions:
            raise ValueError(f"蛊虫 / 其他与顶层词条重名：{sorted(collisions)}")
        gu.pop("其他")
        gu.update(other)


def validate(data):
    if "五域地理" in data or "势力" in data:
        raise ValueError("旧五域分类仍位于顶层")
    realms = data.get("五域资料")
    if not isinstance(realms, dict):
        raise ValueError("缺少五域资料分类")
    if tuple(realms) != REALM_CHAPTERS:
        raise ValueError("五域资料仍含旧资料或缺少保留章节")

    aliens = data.get("异人")
    expected_aliens = [
        "异人设定",
        "毛民",
        "蛋人",
        "墨人",
        "羽民",
        "小人",
        "石人",
        "兽人",
        "鲛人",
        "雪人",
        "菇人",
        "龙人",
    ]
    if not isinstance(aliens, dict) or list(aliens) != expected_aliens:
        raise ValueError("异人词条不完整或顺序错误")
    if any(name.startswith("第") for name in aliens):
        raise ValueError("异人词条仍带有章节编号")

    people = data.get("人物")
    if not isinstance(people, dict) or not people or not all(is_leaf(value) for value in people.values()):
        raise ValueError("人物必须是无细分的直接词条")
    for name in ("元始仙尊", "凤九歌", "狂蛮魔尊"):
        if not is_leaf(people.get(name)):
            raise ValueError(f"人物 / {name}不存在")
    if "九转尊者之“元始仙尊”" not in people["元始仙尊"].get("desc", ""):
        raise ValueError("元始仙尊未并入十尊者资料")
    if "身份地位：" not in people["凤九歌"].get("desc", ""):
        raise ValueError("凤九歌未并入人物篇资料")
    if "狂蛮" not in people["狂蛮魔尊"].get("aliases", []):
        raise ValueError("狂蛮魔尊别名未保留")

    if "人祖传" in data:
        raise ValueError("人祖传分类仍位于百科顶层")
    if "境界流派" in data:
        raise ValueError("旧境界流派分类仍位于百科顶层")
    school = data.get("流派与境界")
    expected_school_entries = [name for name, _desc in SCHOOL_ENTRIES]
    if not isinstance(school, dict) or list(school) != expected_school_entries:
        raise ValueError("流派与境界词条不完整或顺序错误")
    if any(not is_leaf(value) or value.get("section") != "流派设定" for value in school.values()):
        raise ValueError("流派与境界词条格式错误")

    basic = data.get("基本设定", {})
    if not isinstance(basic, dict) or any(
        value.get("section") != "基本设定"
        for _path, _name, value in iter_leaves(basic)
    ):
        raise ValueError("基本设定仍含章节编号来源标签")

    gu = data.get("蛊虫", {})
    if "宿命蛊" not in gu.get("八转", {}) or "宿命蛊" in gu.get("九转", {}):
        raise ValueError("宿命蛊的八转调整未保留")
    if "其他" in gu:
        raise ValueError("蛊虫 / 其他未提升为无细分词条")
    if data.get("仙蛊屋", {}).get("海角阁", {}).get("section") != "":
        raise ValueError("海角阁的空 section 未保留")
    if data.get("洞天秘境", {}).get("洞天", {}).get("长生天", {}).get("section") != "":
        raise ValueError("长生天的空 section 未保留")
    if "其他" in data or "_deleted" in data:
        raise ValueError("最终百科不应保留其他分类或回收站数据")


def restructure(data, source_items):
    before = json.dumps(data, ensure_ascii=False, sort_keys=True)
    legacy_people = data.get("人物")
    if not isinstance(legacy_people, dict):
        raise ValueError("缺少待重建的人物分类")

    preserve_manual_adjustments(data)
    normalize_basic_settings(data)
    realms = build_realms(source_items)
    people = build_people(source_items, legacy_people)
    aliens = build_aliens(source_items)
    school = build_school_settings()

    ordered = {}
    emitted = set()
    for category, value in data.items():
        if category in {"五域地理", "五域资料"}:
            if "五域资料" not in emitted:
                ordered["五域资料"] = realms
                emitted.add("五域资料")
            continue
        if category in {"势力", "人祖传"}:
            continue
        if category == "人物":
            ordered["人物"] = people
            ordered["异人"] = aliens
            emitted.update({"人物", "异人"})
            continue
        if category == "异人":
            continue
        if category in {"境界流派", "流派与境界"}:
            if "流派与境界" not in emitted:
                ordered["流派与境界"] = school
                emitted.add("流派与境界")
            continue
        ordered[category] = value

    if "人物" not in emitted:
        ordered["人物"] = people
        ordered["异人"] = aliens
    if "流派与境界" not in emitted:
        ordered["流派与境界"] = school
    if "五域资料" not in emitted:
        ordered["五域资料"] = realms

    validate(ordered)
    return ordered, json.dumps(ordered, ensure_ascii=False, sort_keys=True) != before


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写入已验证的百科重整结果")
    parser.add_argument("--check", action="store_true", help="仅验证当前百科结构")
    args = parser.parse_args()
    if args.apply and args.check:
        raise SystemExit("--apply 与 --check 不能同时使用")

    data = json.loads(WIKI_PATH.read_text(encoding="utf-8"))
    if args.check:
        validate(data)
        print(f"validated: {count_leaves(data)} entries")
        return

    source = json.loads(LORE_TOC_PATH.read_text(encoding="utf-8"))
    source_items = source.get("items")
    if not isinstance(source_items, list):
        raise SystemExit("资料目录格式错误")
    before = count_leaves(data)
    result, changed = restructure(data, source_items)
    if not changed:
        print(f"already structured: {count_leaves(result)} entries")
        return
    if not args.apply:
        raise SystemExit("运行时加入 --apply 才会写入 wiki.json")
    WIKI_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"restructured: {before} -> {count_leaves(result)} entries")


if __name__ == "__main__":
    main()
