# -*- coding: utf-8 -*-
"""Move the source-backed realm entries into the nested 洞天秘境 taxonomy."""
import argparse
import json
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
WIKI_PATH = BASE / "data_jina2" / "wiki.json"

CAVE_HEAVENS = [
    "琅琊洞天", "宝黄天", "长生天", "繁星洞天", "百足洞天", "凤仙洞天", "天庭洞天",
    "玉露洞天", "气海洞天", "黑凡洞天", "药皇洞天", "白相洞天", "气绝洞天", "夏槎洞天",
    "至尊洞天", "五相洞天", "龙鲸洞天", "九虚洞天", "欺圣洞天", "华文洞天", "兽劫洞天",
]

ARTIFICIAL_REALMS = [
    "石莲岛", "盗天空间", "炼海", "漂游炼巢", "人海", "人山", "人山人海", "血海", "非议峰",
]


def is_leaf(value):
    return isinstance(value, dict) and any(key in value for key in ("intro", "desc", "sections", "aliases"))


def count_leaves(data):
    def walk(node):
        if not isinstance(node, dict):
            return 0
        total = 0
        for value in node.values():
            if is_leaf(value):
                total += 1
            if isinstance(value, dict):
                total += walk(value)
        return total

    return sum(walk(node) for category, node in data.items() if category != "_deleted")


def take_leaf(data, name):
    matches = []

    def walk(node):
        if not isinstance(node, dict):
            return
        for entry_name, value in list(node.items()):
            if entry_name == name and is_leaf(value):
                matches.append((node, entry_name, value))
            elif isinstance(value, dict):
                walk(value)

    for category, node in data.items():
        if category not in ("_deleted", "天地秘境"):
            walk(node)
    if len(matches) != 1:
        raise ValueError(f"{name} should have exactly one current location, found {len(matches)}")
    parent, entry_name, entry = matches[0]
    parent.pop(entry_name)
    return entry


def validate(data):
    realms = data.get("洞天秘境")
    if not isinstance(realms, dict):
        raise ValueError("missing 洞天秘境")
    expected_groups = ["洞天", "天地秘境", "人造天地秘境"]
    if list(realms) != expected_groups:
        raise ValueError(f"unexpected realm groups: {list(realms)}")
    if not set(CAVE_HEAVENS).issubset(realms["洞天"]):
        raise ValueError("洞天 entries are missing source chapter items")
    if not set(ARTIFICIAL_REALMS).issubset(realms["人造天地秘境"]):
        raise ValueError("人造天地秘境 entries are missing source chapter items")
    if len(realms["天地秘境"]) < 22:
        raise ValueError("天地秘境 is missing source chapter items")
    return count_leaves(data)


def restructure(data):
    if "洞天秘境" in data:
        return validate(data)
    top_level_order = list(data)
    previous = data.get("天地秘境")
    if not isinstance(previous, dict):
        raise ValueError("missing top-level 天地秘境")

    before = count_leaves(data)
    if not set(ARTIFICIAL_REALMS).issubset(previous):
        raise ValueError("missing expected 人造天地秘境 entries")
    natural = {name: entry for name, entry in previous.items() if name not in ARTIFICIAL_REALMS}
    if len(natural) != 22:
        raise ValueError("expected 22 天地秘境 entries before migration")
    cave_heavens = {name: take_leaf(data, name) for name in CAVE_HEAVENS}
    data.pop("天地秘境")

    realms = {
        "洞天": cave_heavens,
        "天地秘境": natural,
        "人造天地秘境": {name: previous[name] for name in ARTIFICIAL_REALMS},
    }
    ordered = {}
    for category in top_level_order:
        if category == "天地秘境":
            ordered["洞天秘境"] = realms
        else:
            ordered[category] = data[category]

    after = validate(ordered)
    if before != after:
        raise ValueError(f"entry count changed: {before} -> {after}")
    return ordered


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the validated restructure to wiki.json")
    args = parser.parse_args()
    data = json.loads(WIKI_PATH.read_text(encoding="utf-8"))
    if "洞天秘境" in data:
        print(f"already structured: {validate(data)} entries")
        return
    if not args.apply:
        raise SystemExit("run with --apply to write the restructure")
    result = restructure(data)
    WIKI_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"restructured: {count_leaves(result)} entries")


if __name__ == "__main__":
    main()
