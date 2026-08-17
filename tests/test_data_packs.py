import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app import main as wiki_main


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


def quiz(question, explain, riddle_name="谜题"):
    return {
        "quiz": [
            {
                "type": "person",
                "q": question,
                "options": ["甲", "乙", "丙", "丁"],
                "answer": 0,
                "explain": explain,
            }
        ],
        "riddles": {"person": [{"name": riddle_name, "hints": ["一", "二", "三", "四", "五"]}]},
    }


class DataPackTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.local = self.base / "local-data"
        self.incoming = self.base / "incoming-data"
        self.local.mkdir()
        self.incoming.mkdir()
        self._write_fixture_data(
            self.local,
            {
                "人物": {
                    "上古": {"狂蛮": {"desc": "本地描述"}},
                    "相同": {"desc": "相同描述"},
                }
            },
            quiz("冲突题", "本地解析"),
        )
        self._write_fixture_data(
            self.incoming,
            {
                "人物": {
                    "上古": {"狂蛮": {"desc": "导入描述"}, "新人物": {"desc": "新增描述"}},
                    "相同": {"desc": "相同描述"},
                }
            },
            {
                "quiz": [
                    {
                        "type": "person",
                        "q": "冲突题",
                        "options": ["甲", "乙", "丙", "丁"],
                        "answer": 1,
                        "explain": "导入解析",
                    },
                    {
                        "type": "gu",
                        "q": "新增题",
                        "options": ["甲", "乙", "丙", "丁"],
                        "answer": 0,
                        "explain": "新增解析",
                    },
                ],
                "riddles": {"person": [{"name": "谜题", "hints": ["甲", "乙", "丙", "丁", "戊"]}]},
            },
        )
        self.data_patch = patch.object(wiki_main.config, "DATA_DIR", self.local)
        self.base_patch = patch.object(wiki_main.config, "BASE", self.base)
        self.reload_patch = patch.object(wiki_main, "reload_retriever")
        self.data_patch.start()
        self.base_patch.start()
        self.reload_mock = self.reload_patch.start()
        wiki_main._wiki = None
        wiki_main._quiz = None
        wiki_main._content_mtime.clear()

    def tearDown(self):
        self.reload_patch.stop()
        self.base_patch.stop()
        self.data_patch.stop()
        wiki_main._wiki = None
        wiki_main._quiz = None
        wiki_main._content_mtime.clear()
        self.temp_dir.cleanup()

    def _write_fixture_data(self, directory, wiki, quiz_data):
        write_json(directory / "wiki.json", wiki)
        write_json(directory / "quiz.json", quiz_data)
        write_json(directory / "wiki_categories.json", {"custom": []})
        write_json(directory / "info.json", {"model": "test-model"})

    def _incoming_pack(self, kind="editable", custom_quiz=None):
        with patch.object(wiki_main.config, "DATA_DIR", self.incoming):
            payload = wiki_main._build_data_pack(kind, custom_quiz or [])
        return wiki_main._load_data_pack(payload)

    def _write_valid_wiki_index(self, directory):
        wiki = json.loads((directory / "wiki.json").read_text(encoding="utf-8"))
        meta = wiki_main._wiki_index_metadata(wiki)
        write_json(directory / "wiki" / "meta.json", meta)
        vector_file = directory / "wiki" / "vectors.npy"
        vector_file.parent.mkdir(parents=True, exist_ok=True)
        np.save(vector_file, np.zeros((len(meta), 768), dtype=np.float32))

    def test_preview_reports_wiki_and_quiz_conflicts(self):
        manifest, files = self._incoming_pack(custom_quiz=[{"kind": "quiz", "type": "gu", "q": "浏览器题"}])
        preview = wiki_main._data_pack_preview(manifest, files)

        self.assertEqual(preview["wiki"]["incomingEntries"], 3)
        self.assertEqual(preview["wiki"]["newEntries"], 1)
        self.assertEqual(preview["wiki"]["identicalEntries"], 1)
        self.assertEqual(preview["wiki"]["conflicts"], 1)
        self.assertEqual(preview["wiki"]["conflictSamples"][0]["name"], "狂蛮")
        self.assertEqual(preview["quiz"]["newEntries"], 1)
        self.assertEqual(preview["quiz"]["conflicts"], 2)
        self.assertEqual(preview["customQuizEntries"], 1)

    def test_merge_keeps_local_conflicts_and_adds_new_records(self):
        manifest, files = self._incoming_pack()
        result = wiki_main._apply_data_pack(manifest, files, "merge")
        merged_wiki = json.loads((self.local / "wiki.json").read_text(encoding="utf-8"))
        merged_quiz = json.loads((self.local / "quiz.json").read_text(encoding="utf-8"))

        self.assertEqual(merged_wiki["人物"]["上古"]["狂蛮"]["desc"], "本地描述")
        self.assertEqual(merged_wiki["人物"]["上古"]["新人物"]["desc"], "新增描述")
        self.assertEqual(result["summary"], {"wikiAdded": 1, "wikiConflicts": 1, "quizAdded": 1, "quizConflicts": 2})
        self.assertTrue(result["needsWikiRebuild"])
        self.assertTrue((self.base / result["backup"]).is_file())
        self.assertEqual({item["q"] for item in merged_quiz["quiz"]}, {"冲突题", "新增题"})
        self.assertEqual(merged_quiz["quiz"][0]["answer"], 0)
        self.reload_mock.assert_not_called()

    def test_full_replace_removes_stale_data_files_and_creates_backup(self):
        (self.local / "obsolete.json").write_text("{}", encoding="utf-8")
        (self.local / "wiki").mkdir()
        (self.local / "wiki" / "meta.json").write_text("[]", encoding="utf-8")
        (self.local / "wiki" / "vectors.npy").write_bytes(b"old-index")
        manifest, files = self._incoming_pack(kind="full")
        result = wiki_main._apply_data_pack(manifest, files, "replace")

        written = json.loads((self.local / "wiki.json").read_text(encoding="utf-8"))
        self.assertEqual(written["人物"]["上古"]["狂蛮"]["desc"], "导入描述")
        self.assertFalse((self.local / "obsolete.json").exists())
        self.assertFalse((self.local / "wiki" / "meta.json").exists())
        self.assertFalse((self.local / "wiki" / "vectors.npy").exists())
        self.assertTrue((self.base / result["backup"]).is_file())
        self.assertFalse(result["indexInstalled"])
        self.assertTrue(result["needsWikiRebuild"])
        self.reload_mock.assert_called_once()

    def test_invalid_editable_index_is_not_installed(self):
        (self.local / "wiki").mkdir()
        (self.local / "wiki" / "meta.json").write_text("[]", encoding="utf-8")
        (self.local / "wiki" / "vectors.npy").write_bytes(b"old-index")
        (self.incoming / "wiki").mkdir()
        (self.incoming / "wiki" / "meta.json").write_text("[]", encoding="utf-8")
        (self.incoming / "wiki" / "vectors.npy").write_bytes(b"not-a-numpy-file")
        manifest, files = self._incoming_pack()
        result = wiki_main._apply_data_pack(manifest, files, "replace")

        self.assertFalse(result["indexInstalled"])
        self.assertTrue(result["needsWikiRebuild"])
        self.assertFalse((self.local / "wiki" / "meta.json").exists())
        self.assertFalse((self.local / "wiki" / "vectors.npy").exists())

    def test_matching_index_can_be_reused(self):
        self._write_valid_wiki_index(self.incoming)
        manifest, files = self._incoming_pack()
        index = wiki_main._validate_data_pack_wiki_index(manifest, files)

        self.assertTrue(index["included"])
        self.assertTrue(index["usable"])
        self.assertEqual(index["entries"], 3)
        self.assertEqual(index["dimension"], 768)


if __name__ == "__main__":
    unittest.main()
