import os
import tempfile
import unittest
from unittest.mock import patch

from tinydb import TinyDB
from tinydb.table import Document

import app.database as database_module
from app.database import DatabaseHelper, Diary


class DiaryDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = TinyDB(os.path.join(self.temp_dir.name, "blog_db.json"))
        self.helper = DatabaseHelper()
        self.helper.diary_table = self.db.table("diaries")
        self.snapshot_reasons = []
        self._snapshot_history = database_module._snapshot_history
        database_module._snapshot_history = self.snapshot_reasons.append

    def tearDown(self):
        database_module._snapshot_history = self._snapshot_history
        self.db.close()
        self.temp_dir.cleanup()

    def make_diary(
        self,
        entry_date,
        content="日记正文",
        image_url="",
        created_at="2026-05-18 08:00:00",
        updated_at="2026-05-18 08:00:00",
        location=None,
        weather=None,
    ):
        return Diary(
            entry_date=entry_date,
            content=content,
            image_url=image_url,
            created_at=created_at,
            updated_at=updated_at,
            location=location,
            weather=weather,
        )

    def test_diary_uses_independent_table_and_fixed_fields(self):
        diary = self.make_diary(
            "2026-05-18",
            location={"city": "南京"},
            weather={"condition": "晴"},
        )

        self.assertEqual(self.helper.diary_table.name, "diaries")
        self.assertEqual(
            set(diary.to_dict()),
            {
                "entry_date",
                "content",
                "image_url",
                "created_at",
                "updated_at",
                "location",
                "weather",
            },
        )
        restored = Diary()
        restored.from_dict(diary.to_dict())
        self.assertEqual(restored.entry_date, "2026-05-18")
        self.assertEqual(restored.location, {"city": "南京"})
        self.assertEqual(restored.weather, {"condition": "晴"})
        self.assertEqual(Diary().entry_date, "")
        self.assertEqual(Diary().created_at, "")
        self.assertEqual(Diary().updated_at, "")
        self.assertEqual(Diary().location, {})
        self.assertEqual(Diary().weather, {})
        self.assertIsNot(Diary().location, Diary().location)
        self.assertIsNot(Diary().weather, Diary().weather)

    def test_queries_by_date_and_month_are_sorted_descending(self):
        for entry_date in ("2026-05-03", "2026-05-21", "2026-04-30"):
            self.helper.diary_table.insert(
                self.make_diary(entry_date, content=entry_date).to_dict()
            )

        diary = self.helper.get_diary_by_date("2026-05-03")

        self.assertEqual(diary.content, "2026-05-03")
        self.assertEqual(
            [item.entry_date for item in self.helper.get_all_diaries()],
            ["2026-05-21", "2026-05-03", "2026-04-30"],
        )
        self.assertEqual(
            [item.entry_date for item in self.helper.get_diaries_by_month("2026", 5)],
            ["2026-05-21", "2026-05-03"],
        )

    def test_save_today_diary_updates_existing_entry_without_duplicate(self):
        first = self.make_diary(
            "2026-05-18",
            content="第一版",
            created_at="2026-05-18 08:00:00",
            updated_at="2026-05-18 08:00:00",
        )
        second = self.make_diary(
            "2026-05-18",
            content="第二版",
            image_url="/static/diary/second.jpg",
            created_at="2026-05-18 09:00:00",
            updated_at="2026-05-18 09:00:00",
        )

        inserted = self.helper.save_today_diary(first, "2026-05-18")
        updated = self.helper.save_today_diary(second, "2026-05-18")
        stored = self.helper.get_diary_by_date("2026-05-18")

        self.assertEqual(inserted["operation"], "inserted")
        self.assertEqual(updated["operation"], "updated")
        self.assertEqual(len(self.helper.diary_table.all()), 1)
        self.assertEqual(stored.content, "第二版")
        self.assertEqual(stored.image_url, "/static/diary/second.jpg")
        self.assertEqual(stored.created_at, "2026-05-18 08:00:00")
        self.assertEqual(stored.updated_at, "2026-05-18 09:00:00")
        self.assertEqual(
            self.snapshot_reasons,
            [
                "pre-insert-diary",
                "post-insert-diary",
                "pre-update-diary",
                "post-update-diary",
            ],
        )

    def test_save_today_diary_preserves_or_fills_metadata(self):
        self.helper.save_today_diary(
            self.make_diary(
                "2026-05-18",
                location={"city": "南京"},
                weather={"condition": "晴"},
            ),
            "2026-05-18",
        )
        self.helper.save_today_diary(
            self.make_diary(
                "2026-05-18",
                content="更新正文",
                location={"city": "苏州"},
                weather={"condition": "雨"},
            ),
            "2026-05-18",
        )
        preserved = self.helper.get_diary_by_date("2026-05-18")

        self.helper.save_today_diary(
            self.make_diary("2026-05-19", location={}, weather={}),
            "2026-05-19",
        )
        self.helper.save_today_diary(
            self.make_diary(
                "2026-05-19",
                location={"city": "无锡"},
                weather={"condition": "多云"},
            ),
            "2026-05-19",
        )
        filled = self.helper.get_diary_by_date("2026-05-19")

        self.assertEqual(preserved.location, {"city": "南京"})
        self.assertEqual(preserved.weather, {"condition": "晴"})
        self.assertEqual(filled.location, {"city": "无锡"})
        self.assertEqual(filled.weather, {"condition": "多云"})

    def test_save_today_diary_rejects_historical_date(self):
        with self.assertRaisesRegex(ValueError, "当天"):
            self.helper.save_today_diary(
                self.make_diary("2026-05-17"),
                "2026-05-18",
            )

        self.assertEqual(self.helper.diary_table.all(), [])
        self.assertEqual(self.snapshot_reasons, [])

    def test_save_today_diary_rejects_empty_content(self):
        for content in ("", "   "):
            with self.subTest(content=content):
                with self.assertRaisesRegex(ValueError, "正文"):
                    self.helper.save_today_diary(
                        self.make_diary("2026-05-18", content=content),
                        "2026-05-18",
                    )

        self.assertEqual(self.helper.diary_table.all(), [])

    def test_save_today_diary_rejects_non_diary(self):
        with self.assertRaisesRegex(TypeError, "Diary"):
            self.helper.save_today_diary({"entry_date": "2026-05-18"}, "2026-05-18")

        self.assertEqual(self.helper.diary_table.all(), [])

    def test_save_today_diary_retries_random_document_id(self):
        self.helper.diary_table.insert(Document({"existing": True}, doc_id=4242))

        with patch(
            "app.database.secrets.randbits",
            side_effect=[4242, 4243],
        ):
            response = self.helper.save_today_diary(
                self.make_diary("2026-05-18"),
                "2026-05-18",
            )

        inserted = self.helper.diary_table.get(doc_id=4243)
        self.assertEqual(response["operation"], "inserted")
        self.assertIsNotNone(inserted)
        self.assertEqual(inserted["entry_date"], "2026-05-18")
        self.assertEqual(len(self.helper.diary_table.all()), 2)


if __name__ == "__main__":
    unittest.main()
