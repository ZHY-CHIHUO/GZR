import importlib.util
import json
import unittest
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
WIKI_PATH = BASE / "data_jina2" / "wiki.json"
SCRIPT_PATH = BASE / "scripts" / "add_ancient_battle_formations.py"

spec = importlib.util.spec_from_file_location("add_ancient_battle_formations", SCRIPT_PATH)
formations = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(formations)


class AncientBattleFormationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(WIKI_PATH.read_text(encoding="utf-8"))

    def test_formations_are_under_kill_moves_subgroup(self):
        kills = self.data["杀招"]
        group = kills["上古战阵"]
        self.assertEqual(list(group), list(formations.FORMATIONS))
        self.assertNotIn("四通八达", kills)
        for name, desc in formations.FORMATIONS.items():
            self.assertTrue(group[name]["desc"].startswith(desc))
            self.assertNotIn(name, self.data["其他"])

    def test_existing_four_connections_detail_is_retained(self):
        desc = self.data["杀招"]["上古战阵"]["四通八达"]["desc"]
        self.assertIn("残缺版", desc)
        self.assertIn("核心仙蛊", desc)

    def test_repeated_migration_does_not_duplicate_supplements(self):
        data = json.loads(json.dumps(self.data, ensure_ascii=False))
        before = data["杀招"]["上古战阵"]["四通八达"]["desc"]
        formations.add_ancient_battle_formations(data)
        after = data["杀招"]["上古战阵"]["四通八达"]["desc"]
        self.assertEqual(after, before)

    def test_duplicate_old_text_is_collapsed_when_migrated(self):
        data = {
            "杀招": {"四通八达": {"desc": "旧资料"}},
            "其他": {
                "金梵天圣": {"desc": "上古战阵排行第一位 上古战阵排行第一位"},
            },
        }
        formations.add_ancient_battle_formations(data)
        self.assertEqual(data["杀招"]["上古战阵"]["金梵天圣"]["desc"], "上古战阵排行第一位。")
        self.assertIn("旧资料", data["杀招"]["上古战阵"]["四通八达"]["desc"])


if __name__ == "__main__":
    unittest.main()
