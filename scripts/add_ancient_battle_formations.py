# -*- coding: utf-8 -*-
"""Place the curated ancient battle formations under 杀招 / 上古战阵."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
WIKI_PATH = BASE / "data_jina2" / "wiki.json"

KILL_MOVES = "杀招"
OTHER = "其他"
GROUP = "上古战阵"
FORMATIONS = {
    "金梵天圣": "上古战阵排行第一位。",
    "天婆梭罗": "上古战阵排行第二位。",
    "青城纵横": "上古战阵排行第三位。",
    "七极荒都": "黄金部族中的北斗七仙所创，为平定叛乱，捕捉太古，镇压传奇。",
    "十二生肖": "集齐十二只不同种类的太古年兽方能组合而成，拥有八转高端战力。",
    "四通八达": "以四位蛊仙为阵眼，专擅遁移。",
    "八极": "长生天上古战阵，以八极子为阵眼，将获取的力量分派到各个蛊仙身上，使得八极子战力疯狂暴涨，从七转一路上升到八转精英的层次。且能让八极子思维紧密联系，视野共享，还能共享杀招手段。",
}
LEAF_KEYS = {"intro", "desc", "section", "sections", "aliases"}


def is_leaf(value: object) -> bool:
    return isinstance(value, dict) and any(key in value for key in LEAF_KEYS)


def description(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get("desc") or "").strip()


def normalized(value: str) -> str:
    return " ".join(value.split())


def comparison_key(value: str) -> str:
    """Compare imported prose while ignoring harmless spacing and punctuation."""

    return re.sub(r"[\s，。！？、；：:“”‘’（）()【】…·]", "", value)


def repeats(value: str, canonical: str) -> bool:
    """Recognize duplicated old imports without retaining the duplicate."""

    old = comparison_key(value)
    new = comparison_key(canonical)
    return old in {new, f"{new}{new}"}


def merge_descriptions(canonical: str, previous: list[str]) -> str:
    supplements: list[str] = []
    for old in previous:
        old = old.strip()
        if not old or repeats(old, canonical):
            continue
        if old.startswith(canonical):
            # Preserve the prior supplement without treating its canonical
            # opening as a second source on repeated runs.
            old = old[len(canonical) :].strip()
            if old.startswith("补充资料："):
                old = old.removeprefix("补充资料：").strip()
            if not old:
                continue
        if comparison_key(old) and comparison_key(old) in comparison_key(canonical):
            continue
        if any(comparison_key(old) in comparison_key(item) for item in supplements):
            continue
        supplements.append(old)
    if not supplements:
        return canonical
    return f"{canonical}\n\n补充资料：\n" + "\n\n".join(supplements)


def add_ancient_battle_formations(data: dict[str, object]) -> dict[str, object]:
    kills = data.get(KILL_MOVES)
    other = data.get(OTHER)
    if not isinstance(kills, dict):
        raise ValueError("missing 杀招 category")
    if not isinstance(other, dict):
        raise ValueError("missing 其他 category")

    group = kills.get(GROUP)
    if group is None:
        group = {}
        kills[GROUP] = group
    if not isinstance(group, dict) or is_leaf(group):
        raise ValueError("杀招 / 上古战阵 must be a group")

    moved_from_other: list[str] = []
    moved_from_root: list[str] = []
    for name, canonical in FORMATIONS.items():
        previous: list[str] = []

        existing = group.get(name)
        if existing is not None:
            if not is_leaf(existing):
                raise ValueError(f"杀招 / 上古战阵 / {name} is not a leaf")
            previous.append(description(existing))

        root = kills.get(name)
        if root is not None:
            if not is_leaf(root):
                raise ValueError(f"杀招 / {name} is not a leaf")
            previous.append(description(root))
            del kills[name]
            moved_from_root.append(name)

        old = other.get(name)
        if old is not None:
            if not is_leaf(old):
                raise ValueError(f"其他 / {name} is not a leaf")
            previous.append(description(old))
            del other[name]
            moved_from_other.append(name)

        group[name] = {"desc": merge_descriptions(canonical, previous)}

    return {
        "movedFromOther": moved_from_other,
        "movedFromKillMovesRoot": moved_from_root,
        "formationCount": len(group),
    }


def validate(data: dict[str, object]) -> None:
    kills = data.get(KILL_MOVES)
    other = data.get(OTHER)
    if not isinstance(kills, dict) or not isinstance(other, dict):
        raise ValueError("missing required categories")
    group = kills.get(GROUP)
    if not isinstance(group, dict) or is_leaf(group):
        raise ValueError("missing 杀招 / 上古战阵 group")
    for name, canonical in FORMATIONS.items():
        entry = group.get(name)
        if not is_leaf(entry) or not description(entry).startswith(canonical):
            raise ValueError(f"missing or changed 杀招 / 上古战阵 / {name}")
        if name in other or name in kills:
            raise ValueError(f"duplicate source entry remains for {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the migration to wiki.json")
    args = parser.parse_args()

    data = json.loads(WIKI_PATH.read_text(encoding="utf-8"))
    report = add_ancient_battle_formations(data)
    validate(data)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.apply:
        WIKI_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
