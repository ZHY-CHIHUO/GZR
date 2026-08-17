import json
import unittest
from pathlib import Path


WIKI_PATH = Path(__file__).resolve().parents[1] / "data_jina2" / "wiki.json"

EXPECTED_ENTRIES = [
    "蛊修设定", "开窍设定", "真元", "蛊师晋升", "空窍等级与十绝体", "空窍仙窍承载力", "升仙", "仙窍",
    "人气", "仙窍等级区分", "成尊条件", "天道封锁", "全知全能永生", "吞窍和渡劫", "材料、灵材、仙材",
    "元气与道痕", "转数",
]


class BasicSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(WIKI_PATH.read_text(encoding="utf-8"))

    def test_basic_settings_are_direct_and_ordered(self):
        basic = self.data["基本设定"]
        self.assertNotIn("第一卷", basic)
        self.assertEqual(list(basic), EXPECTED_ENTRIES)
        self.assertEqual(basic["蛊修设定"]["section"], "基本设定")
        self.assertEqual(basic["转数"]["section"], "基本设定")
        self.assertIn("仙窍本源", basic["吞窍和渡劫"]["desc"])
        self.assertIn("天道道痕", basic["元气与道痕"]["desc"])


if __name__ == "__main__":
    unittest.main()
