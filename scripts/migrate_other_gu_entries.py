# -*- coding: utf-8 -*-
"""Move direct top-level Gu entries into the Gu catalogue.

Only names ending in ``蛊`` are candidates.  A rank group is selected only
when the entry itself is explicitly described as that rank; references to a
different Gu, a user of that rank, or a future upgrade do not determine the
candidate's own rank.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
WIKI_PATH = BASE / "data_jina2" / "wiki.json"

OTHER_CATEGORY = "其他"
GU_CATEGORY = "蛊虫"
GU_SUFFIX = "蛊"
RANKS = ("一转", "二转", "三转", "四转", "五转", "六转", "七转", "八转", "九转")
LEAF_KEYS = {"intro", "desc", "section", "sections", "aliases"}
RANK_CHARS = "一二三四五六七八九"

REFERENCE_ENTRIES = {
    "蛊虫介绍": (
        "蛊虫需要喂养，等级越高对于食量和食物质量要求越多越高，但等级越高吃的顿数就越少。\n\n"
        "蛊虫分为“凡蛊”和“仙蛊”。凡蛊单一，能力只有一个；仙蛊唯一，无论几转仙蛊只能有一个。\n\n"
        "因字数限制，详情见词条“蛊”。"
    ),
    "奇蛊榜": (
        "第一位：未知：巨阳仙尊所炼。\n"
        "第三位：春秋蝉：宙道辅助仙蛊，红莲魔尊本命蛊，现古月方源所掌握。\n"
        "第四位：在乎蛊：无极魔尊所炼，现疯魔三怪·胖山所掌握。\n"
        "第五位：气遁蛊。\n"
        "第六位：斗转蛊：乐土仙尊所炼。\n"
        "第七位：通心蛊：星宿仙尊所炼。\n"
        "第八位：仿伪蛊：盗天魔尊所炼，能稍稍突破仙蛊唯一这个常规。只是模仿出来的蛊，威能比不上正品，现巨阳仙尊所掌握。\n"
        "第十位：星眸蛊：星道侦查仙蛊，现星宿仙尊所掌握。\n"
        "第？位：应声虫：音道仙蛊，催发出声，但凡听到此声的存在，只要回应一声，都会沦为奴仆。位列奇蛊榜前十，具体排位不明。"
    ),
    "仙蛊榜": "第六位：天元宝皇莲：元莲仙尊所炼，现古月方源所掌握。",
    "魔蛊榜": "第七位：血神子。",
}


def is_leaf(value: object) -> bool:
    return isinstance(value, dict) and any(key in value for key in LEAF_KEYS)


def entry_text(value: object) -> str:
    """Return searchable user-facing text without inspecting group names."""

    pieces: list[str] = []

    def collect(item: object) -> None:
        if isinstance(item, str):
            pieces.append(item)
        elif isinstance(item, dict):
            for child in item.values():
                collect(child)
        elif isinstance(item, list):
            for child in item:
                collect(child)

    if isinstance(value, dict):
        for key in LEAF_KEYS:
            if key in value:
                collect(value[key])
    return "\n".join(pieces)


def existing_gu_names(node: dict[str, object]) -> set[str]:
    names: set[str] = set()

    def walk(current: object) -> None:
        if not isinstance(current, dict):
            return
        for name, value in current.items():
            if is_leaf(value):
                names.add(name)
            elif isinstance(value, dict):
                walk(value)

    walk(node)
    return names


def explicit_rank(name: str, value: object) -> str | None:
    """Return a rank only when the description identifies this entry's rank.

    Examples that intentionally do *not* match: ``五转蛊师曾使用此蛊`` and
    ``可合炼为三转蛊``.  Those describe another subject, not the entry.
    """

    text = entry_text(value)
    if not text:
        return None

    escaped_name = re.escape(name)
    patterns: Iterable[re.Pattern[str]] = (
        # "每一根金针蛊，都是二转蛊" and equivalent self-descriptions.
        re.compile(
            rf"(?:每一根|此|这|该|本)?{escaped_name}[，、,\s]{{0,12}}"
            rf"(?:(?:都)?是|为|乃|属于|品阶(?:为|是|：|:)|转数(?:为|是|：|:))\s*"
            rf"([{RANK_CHARS}])转(?:仙蛊|凡蛊|蛊)"
        ),
        # A leading "二转水道" or "二转消耗蛊" introduces this Gu directly.
        re.compile(
            rf"(?:^|\n)\s*([{RANK_CHARS}])转(?:仙蛊|凡蛊|"
            rf"[\u4e00-\u9fff]{{1,8}}(?:道|蛊))"
        ),
    )
    for pattern in patterns:
        matched = pattern.search(text)
        if matched:
            return f"{matched.group(1)}转"
    return None


def ensure_rank_groups(gu: dict[str, object]) -> None:
    for rank in RANKS:
        group = gu.get(rank)
        if not isinstance(group, dict) or is_leaf(group):
            raise ValueError(f"蛊虫 / {rank} must be a group before migration")


def add_reference_entries(gu: dict[str, object]) -> list[str]:
    added: list[str] = []
    for name, desc in REFERENCE_ENTRIES.items():
        current = gu.get(name)
        expected = {"desc": desc}
        if current is None:
            gu[name] = expected
            added.append(name)
        elif current != expected:
            raise ValueError(f"refusing to overwrite existing 蛊虫 / {name}")
    return added


def migrate_gu_entries(data: dict[str, object]) -> dict[str, object]:
    other = data.get(OTHER_CATEGORY)
    gu = data.get(GU_CATEGORY)
    if not isinstance(other, dict):
        raise ValueError("missing top-level 其他 category")
    if not isinstance(gu, dict):
        raise ValueError("missing top-level 蛊虫 category")
    ensure_rank_groups(gu)

    known_names = existing_gu_names(gu)
    report: dict[str, object] = {
        "moved": 0,
        "root": [],
        "ranked": {rank: [] for rank in RANKS},
        "skipped": [],
    }

    for name in list(other):
        if not name.endswith(GU_SUFFIX):
            continue
        entry = other[name]
        if not is_leaf(entry):
            report["skipped"].append({"name": name, "reason": "not a leaf entry"})
            continue
        if name in known_names:
            report["skipped"].append({"name": name, "reason": "name already exists under 蛊虫"})
            continue

        rank = explicit_rank(name, entry)
        target = gu if rank is None else gu[rank]
        if not isinstance(target, dict):
            raise ValueError(f"蛊虫 / {rank} is not a group")
        target[name] = entry
        del other[name]
        known_names.add(name)
        report["moved"] += 1
        if rank is None:
            report["root"].append(name)
        else:
            report["ranked"][rank].append(name)

    report["referenceAdded"] = add_reference_entries(gu)
    return report


def validate(data: dict[str, object]) -> None:
    other = data.get(OTHER_CATEGORY)
    gu = data.get(GU_CATEGORY)
    if not isinstance(other, dict) or not isinstance(gu, dict):
        raise ValueError("missing required categories")
    ensure_rank_groups(gu)
    remaining = [name for name in other if name.endswith(GU_SUFFIX)]
    if remaining:
        raise ValueError(f"unmigrated top-level 蛊虫 entries: {', '.join(remaining)}")
    for name, desc in REFERENCE_ENTRIES.items():
        if gu.get(name) != {"desc": desc}:
            raise ValueError(f"missing or changed 蛊虫 / {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the migration to wiki.json")
    args = parser.parse_args()

    data = json.loads(WIKI_PATH.read_text(encoding="utf-8"))
    report = migrate_gu_entries(data)
    validate(data)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.apply:
        WIKI_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
