import importlib.util
import json
import unittest
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
WIKI_PATH = BASE / "data_jina2" / "wiki.json"
SCRIPT_PATH = BASE / "scripts" / "migrate_other_gu_entries.py"

spec = importlib.util.spec_from_file_location("migrate_other_gu_entries", SCRIPT_PATH)
migration = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(migration)


class GuCatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(WIKI_PATH.read_text(encoding="utf-8"))

    def test_top_level_other_no_longer_contains_gu_entries(self):
        self.assertFalse([name for name in self.data["其他"] if name.endswith("蛊")])

    def test_explicit_rank_entries_are_grouped_without_false_positives(self):
        second_rank = self.data["蛊虫"]["二转"]
        for name in ("金针蛊", "偷袭蛊", "水壳蛊", "焦雷土豆蛊", "二胎蛊", "赶尸蛊", "双窍火炉蛊"):
            self.assertIn(name, second_rank)

        # These descriptions mention another Gu or Gu master, not their own rank.
        for name in ("火爪蛊", "土堆蛊", "猴语蛊", "照影蛊"):
            self.assertIn(name, self.data["蛊虫"])

    def test_new_gu_reference_entries_are_direct_entries(self):
        gu = self.data["蛊虫"]
        for name in ("蛊虫介绍", "奇蛊榜", "仙蛊榜", "魔蛊榜"):
            self.assertIn(name, gu)
            self.assertIn("desc", gu[name])

    def test_migration_keeps_ambiguous_rank_references_at_root(self):
        data = {
            "其他": {
                "测试蛊": {"desc": "此蛊可合炼为三转蛊。"},
                "二转测试蛊": {"desc": "二转火道，可用于测试。"},
            },
            "蛊虫": {rank: {} for rank in migration.RANKS},
        }
        report = migration.migrate_gu_entries(data)

        self.assertEqual(report["moved"], 2)
        self.assertIn("测试蛊", data["蛊虫"])
        self.assertIn("二转测试蛊", data["蛊虫"]["二转"])
        self.assertEqual(data["其他"], {})


if __name__ == "__main__":
    unittest.main()
