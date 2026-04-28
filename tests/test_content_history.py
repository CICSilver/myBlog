import json
import os
import tempfile
import unittest

from app.content_history import list_history, restore_snapshot, snapshot_content_db


class ContentHistoryTest(unittest.TestCase):
    def test_snapshot_records_manifest_and_restores_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "blog_db.json")
            history_dir = os.path.join(temp_dir, "history")
            restore_path = os.path.join(temp_dir, "restored.json")

            with open(db_path, "w", encoding="utf-8") as db_file:
                json.dump({"blogs": {"1": {"title": "first"}}}, db_file)

            entry = snapshot_content_db(db_path, "unit-test", history_dir=history_dir)
            entries = list_history(history_dir)

            self.assertIsNotNone(entry)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["reason"], "unit-test")
            self.assertTrue(os.path.exists(entries[0]["path"]))

            restore_snapshot(entries[0]["path"], restore_path)
            with open(restore_path, "r", encoding="utf-8") as restored:
                self.assertEqual(json.load(restored)["blogs"]["1"]["title"], "first")

    def test_prunes_old_snapshots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "blog_db.json")
            history_dir = os.path.join(temp_dir, "history")

            for index in range(3):
                with open(db_path, "w", encoding="utf-8") as db_file:
                    json.dump({"index": index}, db_file)
                snapshot_content_db(
                    db_path,
                    "unit-test-{0}".format(index),
                    history_dir=history_dir,
                    max_snapshots=2,
                )

            entries = list_history(history_dir)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["reason"], "unit-test-2")
            self.assertEqual(entries[1]["reason"], "unit-test-1")


if __name__ == "__main__":
    unittest.main()
