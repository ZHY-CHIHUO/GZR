import json
import unittest
from pathlib import Path


WIKI_PATH = Path(__file__).resolve().parents[1] / "data_jina2" / "wiki.json"

CAVE_HEAVENS = {
    "琅琊洞天", "宝黄天", "长生天", "繁星洞天", "百足洞天", "凤仙洞天", "天庭洞天",
    "玉露洞天", "气海洞天", "黑凡洞天", "药皇洞天", "白相洞天", "气绝洞天", "夏槎洞天",
    "至尊洞天", "五相洞天", "龙鲸洞天", "九虚洞天", "欺圣洞天", "华文洞天", "兽劫洞天",
}

ARTIFICIAL_REALMS = {
    "石莲岛", "盗天空间", "炼海", "漂游炼巢", "人海", "人山", "人山人海", "血海", "非议峰",
}


def is_leaf(value):
    return isinstance(value, dict) and any(key in value for key in ("intro", "desc", "sections", "aliases"))


def count_leaves(data):
    def walk(node):
        if not isinstance(node, dict):
            return 0
        return sum((1 if is_leaf(value) else 0) + walk(value) for value in node.values() if isinstance(value, dict))

    return sum(walk(node) for category, node in data.items() if category != "_deleted")


class WikiStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(WIKI_PATH.read_text(encoding="utf-8"))

    def test_realm_taxonomy_is_source_backed_and_lossless(self):
        self.assertNotIn("天地秘境", self.data)
        realms = self.data["洞天秘境"]
        self.assertEqual(list(realms), ["洞天", "天地秘境", "人造天地秘境"])
        self.assertTrue(CAVE_HEAVENS.issubset(realms["洞天"]))
        self.assertGreaterEqual(len(realms["天地秘境"]), 22)
        self.assertTrue(ARTIFICIAL_REALMS.issubset(realms["人造天地秘境"]))
        self.assertGreaterEqual(sum(len(group) for group in realms.values()), 52)
        self.assertGreater(count_leaves(self.data), 0)
        self.assertEqual(realms["洞天"]["长生天"]["section"], "")

    def test_existing_manual_wiki_adjustments_are_preserved(self):
        gu_ranks = self.data["蛊虫"]
        self.assertIn("宿命蛊", gu_ranks["八转"])
        self.assertNotIn("宿命蛊", gu_ranks.get("九转", {}))
        self.assertNotIn("其他", gu_ranks)
        self.assertTrue(is_leaf(gu_ranks["原文"]))
        self.assertEqual(self.data["仙蛊屋"]["海角阁"]["section"], "")
        deleted = next(item for item in self.data["_deleted"] if item["name"] == "免试")
        self.assertEqual((deleted["cat"], deleted["path"]), ("五域地理", []))

    def test_realm_people_alien_and_school_categories_are_restructured(self):
        self.assertNotIn("五域地理", self.data)
        self.assertNotIn("势力", self.data)
        realms = self.data["五域资料"]
        self.assertEqual(
            list(realms),
            ["界壁", "中州", "北原", "南疆", "西漠", "东海", "五域特色与文化活动", "五域优劣对比"],
        )
        self.assertNotIn("补充资料", realms)
        self.assertNotIn("五域势力", realms)
        aliens = self.data["异人"]
        self.assertEqual(
            list(aliens),
            ["异人设定", "毛民", "蛋人", "墨人", "羽民", "小人", "石人", "兽人", "鲛人", "雪人", "菇人", "龙人"],
        )
        self.assertNotIn("第十二章龙人", aliens)

        people = self.data["人物"]
        self.assertGreaterEqual(len(people), 790)
        self.assertTrue(all(is_leaf(value) for value in people.values()))
        self.assertIn("九转尊者之“元始仙尊”", people["元始仙尊"]["desc"])
        self.assertIn("身份地位：", people["凤九歌"]["desc"])
        self.assertIn("狂蛮", people["狂蛮魔尊"].get("aliases", []))

        self.assertNotIn("人祖传", self.data)
        self.assertNotIn("境界流派", self.data)
        school = self.data["流派与境界"]
        self.assertEqual(
            list(school),
            ["流派", "境界", "道主", "流派上限", "各种流派", "流派开创者"],
        )
        self.assertTrue(all(is_leaf(value) and value.get("section") == "流派设定" for value in school.values()))


if __name__ == "__main__":
    unittest.main()
