import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main as wiki_main


class WikiCategoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.wiki_file = self.data_dir / "wiki.json"
        self.wiki_file.write_text(
            json.dumps(
                {
                    "现有分类": {"已有词条": {"desc": "受保护的现有资料"}},
                    "空现有分类": {},
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

    def test_only_empty_custom_categories_can_be_deleted(self):
        created = wiki_main.wiki_category_create(wiki_main.WikiCategoryReq(name="自定义分类"))
        self.assertTrue(created["ok"])
        self.assertIn("自定义分类", self.data())
        self.assertIn("自定义分类", wiki_main.wiki_all()["customCategories"])

        protected = wiki_main.wiki_category_delete(wiki_main.WikiCategoryReq(name="空现有分类"))
        self.assertEqual(protected.status_code, 403)
        self.assertIn("空现有分类", self.data())

        added = wiki_main.wiki_update(
            wiki_main.WikiEntryReq(cat="自定义分类", name="临时词条", desc="用于分类删除测试")
        )
        self.assertTrue(added["ok"])

        nonempty = wiki_main.wiki_category_delete(wiki_main.WikiCategoryReq(name="自定义分类"))
        self.assertEqual(nonempty.status_code, 409)

        deleted_entry = wiki_main.wiki_update(
            wiki_main.WikiEntryReq(delete=True, cat="自定义分类", name="临时词条", path=[])
        )
        self.assertTrue(deleted_entry["ok"])
        self.assertEqual(self.data()["自定义分类"], {})

        deleted_category = wiki_main.wiki_category_delete(wiki_main.WikiCategoryReq(name="自定义分类"))
        self.assertTrue(deleted_category["ok"])
        self.assertNotIn("自定义分类", self.data())

    def test_entry_cannot_implicitly_create_a_category(self):
        result = wiki_main.wiki_update(
            wiki_main.WikiEntryReq(cat="未创建分类", name="词条", desc="不应创建顶层分类")
        )
        self.assertEqual(result.status_code, 404)
        self.assertNotIn("未创建分类", self.data())


if __name__ == "__main__":
    unittest.main()
