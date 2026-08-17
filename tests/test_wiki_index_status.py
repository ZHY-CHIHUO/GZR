import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app import main as wiki_main


class WikiIndexStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.patch = patch.object(wiki_main.config, "DATA_DIR", self.data_dir)
        self.patch.start()
        self.wiki = {"人物": {"上古": {"狂蛮": {"desc": "力道尊者"}}}}
        (self.data_dir / "wiki").mkdir()
        (self.data_dir / "wiki.json").write_text(json.dumps(self.wiki, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.patch.stop()
        self.temp_dir.cleanup()

    def write_index(self, shape=(1, 768), meta=None):
        expected = wiki_main._wiki_index_metadata(self.wiki)
        (self.data_dir / "wiki" / "meta.json").write_text(
            json.dumps(expected if meta is None else meta, ensure_ascii=False), encoding="utf-8"
        )
        np.save(self.data_dir / "wiki" / "vectors.npy", np.zeros(shape, dtype=np.float32))

    def test_matching_index_is_reported_as_valid(self):
        self.write_index()
        status = wiki_main._wiki_index_disk_status()

        self.assertTrue(status["available"])
        self.assertTrue(status["valid"])
        self.assertEqual(status["entries"], 1)
        self.assertEqual(status["dimension"], 768)

    def test_wrong_dimension_requires_rebuild(self):
        self.write_index(shape=(1, 512))
        status = wiki_main._wiki_index_disk_status()

        self.assertTrue(status["available"])
        self.assertFalse(status["valid"])
        self.assertIn("768", status["reason"])

    def test_successful_background_build_reloads_the_retriever(self):
        with wiki_main._wiki_index_job_lock:
            old_job = dict(wiki_main._wiki_index_job)
            wiki_main._wiki_index_job.update({"state": "running", "error": "", "output": ""})
        try:
            with patch.object(
                wiki_main.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout="built", stderr=""),
            ) as run, patch.object(wiki_main, "reload_retriever") as reload, patch.object(
                wiki_main,
                "_wiki_index_disk_status",
                return_value={"available": True, "valid": True, "entries": 1, "dimension": 768},
            ):
                wiki_main._run_wiki_index_build()

            job = wiki_main._wiki_index_job_snapshot()
            self.assertEqual(job["state"], "completed")
            self.assertEqual(job["output"], "built")
            run.assert_called_once()
            reload.assert_called_once()
        finally:
            with wiki_main._wiki_index_job_lock:
                wiki_main._wiki_index_job.clear()
                wiki_main._wiki_index_job.update(old_job)


if __name__ == "__main__":
    unittest.main()
