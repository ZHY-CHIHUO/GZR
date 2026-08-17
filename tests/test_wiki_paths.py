import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main as wiki_main


class WikiPathTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.wiki_file = self.data_dir / "wiki.json"
        self.wiki_file.write_text(
            json.dumps(
                {
                    "人物": {
                        "上古": {"狂蛮": {"desc": "上古原始描述"}},
                        "近古": {"狂蛮": {"desc": "近古原始描述"}},
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.data_dir_patch = patch.object(wiki_main.config, "DATA_DIR", self.data_dir)
        self.data_dir_patch.start()
        wiki_main._wiki = None
        wiki_main._content_mtime.clear()

    def tearDown(self):
        self.data_dir_patch.stop()
        wiki_main._wiki = None
        wiki_main._content_mtime.clear()
        self.temp_dir.cleanup()

    def data(self):
        return json.loads(self.wiki_file.read_text(encoding="utf-8"))

    def test_nested_edit_delete_and_restore_use_full_path(self):
        edited = wiki_main.wiki_update(
            wiki_main.WikiEntryReq(
                cat="人物",
                name="狂蛮",
                path=["上古"],
                old_cat="人物",
                old_name="狂蛮",
                old_path=["上古"],
                desc="上古编辑后描述",
            )
        )
        self.assertTrue(edited["ok"])
        self.assertEqual(self.data()["人物"]["上古"]["狂蛮"]["desc"], "上古编辑后描述")
        self.assertEqual(self.data()["人物"]["近古"]["狂蛮"]["desc"], "近古原始描述")

        deleted = wiki_main.wiki_update(
            wiki_main.WikiEntryReq(delete=True, cat="人物", name="狂蛮", path=["上古"])
        )
        self.assertTrue(deleted["ok"])
        after_delete = self.data()
        self.assertNotIn("上古", after_delete["人物"])
        self.assertEqual(after_delete["人物"]["近古"]["狂蛮"]["desc"], "近古原始描述")
        self.assertEqual(after_delete["_deleted"][0]["path"], ["上古"])

        wrong_path = wiki_main.wiki_restore(
            wiki_main.WikiTrashReq(cat="人物", name="狂蛮", path=["近古"])
        )
        self.assertEqual(wrong_path.status_code, 404)

        restored = wiki_main.wiki_restore(
            wiki_main.WikiTrashReq(cat="人物", name="狂蛮", path=["上古"])
        )
        self.assertTrue(restored["ok"])
        after_restore = self.data()
        self.assertEqual(after_restore["人物"]["上古"]["狂蛮"]["desc"], "上古编辑后描述")
        self.assertEqual(after_restore["人物"]["近古"]["狂蛮"]["desc"], "近古原始描述")


if __name__ == "__main__":
    unittest.main()
