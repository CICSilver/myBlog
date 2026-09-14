import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.database import Blog, DatabaseHelper
from app.sqlite_store import SQLiteStore, backup_sqlite, read_documents
from app.content_history import list_history, restore_snapshot, snapshot_content_db


def make_blog(slug):
    row = Blog(html_title=slug, title=slug, content="body", category="notes")
    row.year, row.month = "2026", "9"
    return row


def worker(path, prefix):
    helper = DatabaseHelper(SQLiteStore(path))
    with patch("app.database._snapshot_history"):
        for number in range(8):
            helper.insert_blog(make_blog(prefix + str(number)))


def interrupted_writer(path):
    store = SQLiteStore(path)
    with store.transaction():
        store.table("devices").insert({"uncommitted": True})
        os._exit(42)


class SQLiteMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "db.sqlite3"
        self.a, self.b = SQLiteStore(self.path), SQLiteStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_workers_read_fresh_and_allocate_serial_ids(self):
        a, b = DatabaseHelper(self.a), DatabaseHelper(self.b)
        with patch("app.database._snapshot_history"):
            a.insert_blog(make_blog("one"))
            self.assertEqual(a.get_specify_blog("2026", "9", "one").title, "one")
            row = b.get_specify_blog("2026", "9", "one")
            row.title = "changed"
            b.update_blog(row)
            self.assertEqual(a.get_specify_blog("2026", "9", "one").title, "changed")
            b.insert_blog(make_blog("two"))
            a.insert_blog(make_blog("three"))
        self.assertEqual(len(a.blog_table.all()), 3)
        self.assertEqual(a.category_table.all()[0]["num"], 3)

    def test_negative_query_does_not_allow_duplicate_url(self):
        a, b = DatabaseHelper(self.a), DatabaseHelper(self.b)
        self.assertIsNone(a.get_specify_blog("2026", "9", "same"))
        with patch("app.database._snapshot_history"):
            b.insert_blog(make_blog("same"))
            result = a.insert_blog(make_blog("same"))
        self.assertEqual(result["html_title"], "same_1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.a.table("blogs").insert(make_blog("same").to_dict())

    def test_failure_rolls_back_all_tables_and_post_callbacks(self):
        a = DatabaseHelper(self.a)
        called = []
        with patch("app.database._snapshot_history"):
            with patch.object(a.blog_table, "insert", side_effect=RuntimeError("failure")):
                with self.assertRaises(RuntimeError):
                    a.insert_blog(make_blog("one"))
        self.assertEqual(self.a.export(), {})
        with self.assertRaises(RuntimeError):
            with self.a.transaction():
                self.a.table("devices").insert({"value": 1})
                self.a.after_commit(lambda: called.append(True))
                raise RuntimeError()
        self.assertEqual(called, [])
        self.assertEqual(self.a.export(), {})

    def test_two_process_writers_preserve_rows_and_counts(self):
        self.a.export()
        context = multiprocessing.get_context("spawn")
        processes = [context.Process(target=worker, args=(str(self.path), prefix)) for prefix in ("a", "b")]
        for process in processes:
            process.start()
        for process in processes:
            process.join(45)
            if process.is_alive():
                process.terminate()
                process.join()
                self.fail("Writer hung")
            self.assertEqual(process.exitcode, 0)
        result = self.a.export()
        self.assertEqual(len(result["blogs"]), 16)
        self.assertEqual(next(iter(result["categories"].values()))["num"], 16)

    def test_backup_captures_wal_and_only_committed_state(self):
        self.a.table("devices").insert({"version": 1})
        connection = sqlite3.connect(self.path)
        self.assertEqual(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        connection.close()
        target = self.root / "backup.sqlite3"
        with self.a.transaction():
            self.a.table("devices").insert({"version": 2})
            backup_sqlite(self.path, target)
        self.assertEqual(len(read_documents(target)["devices"]), 1)
        target2 = self.root / "backup2.sqlite3"
        backup_sqlite(self.path, target2)
        self.assertEqual(len(read_documents(target2)["devices"]), 2)

    def test_production_default_uses_rollback_journal(self):
        self.a.export()
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        finally:
            connection.close()

    def test_process_exit_rolls_back_uncommitted_write(self):
        self.a.table("devices").insert({"committed": True})
        process = multiprocessing.get_context("spawn").Process(target=interrupted_writer, args=(str(self.path),))
        process.start()
        process.join(30)
        if process.is_alive():
            process.terminate()
            process.join()
            self.fail("Interrupted writer hung")
        self.assertEqual(process.exitcode, 42)
        self.assertEqual([dict(row) for row in self.a.table("devices").all()], [{"committed": True}])

    def test_archive_month_counts_follow_article_move(self):
        helper = DatabaseHelper(self.a)
        with patch("app.database._snapshot_history"):
            helper.insert_blog(make_blog("one"))
            row = helper.get_specify_blog("2026", "9", "one")
            row.month = "10"
            helper.update_blog(row, original_key=("2026", "9", "one"))
        counts = {item["month"]: item["num"] for item in helper.get_all_date()}
        self.assertEqual(counts, {"9": 0, "10": 1})

    def test_post_history_is_committed_state_and_rollback_has_no_post(self):
        history = str(self.root / "history")
        self.a.table("devices").insert({"version": 1})
        with self.a.transaction():
            self.a.table("devices").insert({"version": 2})
            snapshot_content_db(self.a.path, "post-update", history_dir=history, source=self.a)
            self.assertEqual(list_history(history), [])
        entry = list_history(history)[0]
        self.assertEqual(len(read_documents(entry["path"])["devices"]), 2)
        with self.assertRaises(RuntimeError):
            with self.a.transaction():
                self.a.table("devices").insert({"version": 3})
                snapshot_content_db(self.a.path, "post-update", history_dir=history, source=self.a)
                raise RuntimeError()
        self.assertEqual(len(list_history(history)), 1)

    def test_restore_json_and_sqlite_over_corrupt_database(self):
        source = self.root / "legacy.json"
        source.write_text(json.dumps({"devices": {"42": {"unknown": [1, "x"]}}}))
        self.path.write_bytes(b"broken database")
        restore_snapshot(source, self.path, service_stopped=True)
        self.assertEqual(read_documents(self.path), read_documents(source))
        self.assertTrue(list(self.root.glob("db.sqlite3.pre-restore-*")))
        entry = snapshot_content_db(self.path, "manual", history_dir=str(self.root / "history"))
        self.assertTrue(entry["path"].endswith(".sqlite3"))
        restored = self.root / "restored.sqlite3"
        restore_snapshot(entry["path"], restored, service_stopped=True)
        self.assertEqual(read_documents(restored), read_documents(source))

    def test_restore_rejects_tampered_snapshot_and_keeps_current_database(self):
        self.a.table("devices").insert({"x": 1})
        entry = snapshot_content_db(self.path, "manual", history_dir=str(self.root / "history"), source=self.a)
        Path(entry["path"]).write_text('{"devices": {}}')
        with self.assertRaisesRegex(ValueError, "checksum"):
            restore_snapshot(entry["path"], self.path, service_stopped=True)
        self.assertEqual(len(self.a.table("devices").all()), 1)


if __name__ == "__main__":
    unittest.main()
