from datetime import date, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import backup_to_drive as backup


def stamps_back_from(day, count):
    return [(day - timedelta(days=offset)).strftime("%Y%m%dT043000Z") for offset in range(count)]


def config(**overrides):
    settings = {
        "MYBLOG_RCLONE": "/opt/myblog-backup/run-rclone",
        "MYBLOG_BACKUP_REMOTE": "myblog_crypt:baselines",
        "MYBLOG_BACKUP_KEEP_DAILY": 7,
        "MYBLOG_BACKUP_KEEP_WEEKLY": 4,
        "MYBLOG_BACKUP_KEEP_LOCAL": 2,
        "MYBLOG_BACKUP_PINNED": [],
        "MYBLOG_BACKUP_MIN_REMOTE": 3,
        "MYBLOG_PYTHON": sys.executable,
    }
    settings.update(overrides)
    return settings


class NamingTests(unittest.TestCase):
    def test_archive_names_split_into_stamp_and_kind(self):
        for name, expected in [
            ("baseline-20260919T040632Z-full.tar.gz", ("20260919T040632Z", "full")),
            ("baseline-20260919T040632Z-content-history.tar.gz", ("20260919T040632Z", "content-history")),
        ]:
            self.assertEqual(backup.stamp_of(name), expected)

    def test_unexpected_names_are_refused_rather_than_guessed(self):
        for name in ["full.tar.gz", "baseline-20260919T040632Z.tar.gz", "baseline-x-full.tgz"]:
            with self.assertRaises(ValueError):
                backup.stamp_of(name)


class RetentionTests(unittest.TestCase):
    def test_keeps_daily_window_weekly_representatives_and_pinned(self):
        stamps = stamps_back_from(date(2026, 9, 19), 40)
        pinned = {stamps[-1]}
        keep = backup.retain(stamps, 7, 4, pinned)
        self.assertTrue(set(sorted(stamps, reverse=True)[:7]) <= keep)
        self.assertLessEqual(len(keep), 7 + 4 + len(pinned))
        weeks = {backup.parse_stamp(stamp).isocalendar()[:2] for stamp in keep}
        self.assertGreaterEqual(len(weeks), 4)

    def test_pinned_survives_however_old_it_is(self):
        stamps = stamps_back_from(date(2026, 9, 19), 40) + ["20260914T064414Z"]
        keep = backup.retain(stamps, 7, 4, {"20260914T064414Z"})
        self.assertIn("20260914T064414Z", keep)

    def test_a_stamp_outside_every_window_is_dropped(self):
        stamps = stamps_back_from(date(2026, 9, 19), 40)
        self.assertNotIn(min(stamps), backup.retain(stamps, 7, 4, set()))


class PruneRemoteTests(unittest.TestCase):
    def prune(self, stamps, current, **overrides):
        calls = []

        def fake_rclone(settings, *args, **kwargs):
            calls.append(tuple(args))
            return ""

        with patch.object(backup, "remote_stamps", return_value=list(stamps)), \
             patch.object(backup, "rclone", fake_rclone):
            removed = backup.prune_remote(config(**overrides), current)
        return removed, calls

    def test_stops_before_dropping_below_the_minimum(self):
        stamps = stamps_back_from(date(2026, 9, 19), 5)
        removed, _ = self.prune(stamps, stamps[0], MYBLOG_BACKUP_KEEP_DAILY=1,
                                MYBLOG_BACKUP_KEEP_WEEKLY=0, MYBLOG_BACKUP_MIN_REMOTE=3)
        self.assertEqual(len(stamps) - len(removed), 3)

    def test_never_removes_the_newest_or_the_run_that_just_uploaded(self):
        stamps = stamps_back_from(date(2026, 9, 19), 20)
        removed, _ = self.prune(stamps, stamps[0], MYBLOG_BACKUP_KEEP_DAILY=1,
                                MYBLOG_BACKUP_KEEP_WEEKLY=0, MYBLOG_BACKUP_MIN_REMOTE=0)
        self.assertNotIn(max(stamps), removed)
        self.assertNotIn(stamps[0], removed)

    def test_purges_whole_stamp_directories_under_the_configured_remote(self):
        stamps = stamps_back_from(date(2026, 9, 19), 20)
        removed, calls = self.prune(stamps, stamps[0], MYBLOG_BACKUP_MIN_REMOTE=0)
        self.assertTrue(removed)
        for stamp in removed:
            self.assertIn(("purge", "myblog_crypt:baselines/" + stamp), calls)


class CaptureTests(unittest.TestCase):
    def test_hands_the_open_lock_descriptor_to_the_bundler(self):
        """create_recovery_bundle.py takes the same lock; without the inherited
        descriptor it would block forever on a lock this process already holds."""
        seen = {}

        def fake_run(args, **kwargs):
            seen.update(env=kwargs.get("env") or {}, pass_fds=kwargs.get("pass_fds"))
            return "SERVICE_HEALTHY mode=online\nBASELINE_COMPLETE"

        with tempfile.TemporaryDirectory() as folder, \
             patch.object(backup, "run", fake_run), \
             patch.object(backup, "verify_bundle_output", lambda text: []):
            backup.capture(Path(folder), config(), Path(folder) / "out", 7)
        self.assertEqual(seen["env"].get("MYBLOG_MAINTENANCE_FD"), "7")
        self.assertEqual(seen["pass_fds"], (7,))

    def test_capture_without_the_completion_marker_is_a_failure(self):
        partial = '{"archive": "/tmp/baseline-20260919T040632Z-full.tar.gz", "size": 1, "sha256": "aa"}'
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(backup, "run", lambda *args, **kwargs: partial), \
             patch.object(backup, "verify_bundle_output", lambda text: []):
            with self.assertRaises(RuntimeError):
                backup.capture(Path(folder), config(), Path(folder) / "out", 7)


class UploadTests(unittest.TestCase):
    def receipts(self, folder):
        path = Path(folder) / "baseline-20260919T040632Z-full.tar.gz"
        path.write_bytes(b"payload")
        return [{"archive": str(path), "size": 7, "sha256": "aa"}]

    def test_records_the_remote_path_after_a_matching_read_back(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(backup, "rclone", lambda *args, **kwargs: ""), \
                 patch.object(backup, "remote_digest", return_value=("aa", 7)):
                entries = backup.upload(config(), self.receipts(folder))
        self.assertEqual(entries, [{
            "remote": "myblog_crypt:baselines/20260919T040632Z/full.tar.gz",
            "filename": "full.tar.gz", "size": 7, "sha256": "aa",
        }])

    def test_a_mismatched_read_back_deletes_the_object_and_fails(self):
        for digest, size in [("bb", 7), ("aa", 6)]:
            with self.subTest(digest=digest, size=size):
                calls = []
                with tempfile.TemporaryDirectory() as folder:
                    with patch.object(backup, "rclone", lambda s, *a, **k: calls.append(tuple(a)) or ""), \
                         patch.object(backup, "remote_digest", return_value=(digest, size)):
                        with self.assertRaises(RuntimeError):
                            backup.upload(config(), self.receipts(folder))
                self.assertIn(("deletefile", "myblog_crypt:baselines/20260919T040632Z/full.tar.gz"), calls)


class PruneLocalTests(unittest.TestCase):
    def build(self, folder, stamps):
        output = Path(folder)
        for stamp in stamps:
            for kind in backup.ARCHIVE_KINDS:
                (output / ("baseline-" + stamp + "-" + kind + ".tar.gz")).write_bytes(b"x")
            (output / ("receipt-" + stamp + ".json")).write_text("[]", encoding="utf-8")
            staging = output / ("baseline-" + stamp)
            staging.mkdir()
            (staging / "full").mkdir()
        return output

    def test_keeps_the_newest_few_plus_pinned_and_the_current_run(self):
        stamps = stamps_back_from(date(2026, 9, 19), 6)
        pinned = stamps[-1]
        with tempfile.TemporaryDirectory() as folder:
            output = self.build(folder, stamps)
            removed = backup.prune_local(output, config(MYBLOG_BACKUP_PINNED=[pinned]), stamps[0])
            survivors = {backup.stamp_of(path.name)[0] for path in output.glob("baseline-*.tar.gz")}
        self.assertEqual(survivors, set(stamps[:2]) | {pinned})
        self.assertNotIn(pinned, removed)

    def test_removes_the_uncompressed_staging_trees_the_bundler_leaves_behind(self):
        stamps = stamps_back_from(date(2026, 9, 19), 2)
        with tempfile.TemporaryDirectory() as folder:
            output = self.build(folder, stamps)
            backup.prune_local(output, config(), stamps[0])
            self.assertEqual([path.name for path in output.glob("baseline-*") if path.is_dir()], [])
            self.assertTrue((output / ("baseline-" + stamps[0] + "-full.tar.gz")).exists())

    def test_a_dropped_stamp_takes_its_receipt_with_it(self):
        stamps = stamps_back_from(date(2026, 9, 19), 4)
        with tempfile.TemporaryDirectory() as folder:
            output = self.build(folder, stamps)
            removed = backup.prune_local(output, config(MYBLOG_BACKUP_KEEP_LOCAL=1), stamps[0])
            for stamp in removed:
                self.assertFalse((output / ("receipt-" + stamp + ".json")).exists())
            self.assertTrue((output / ("receipt-" + stamps[0] + ".json")).exists())


class OutputLocationTests(unittest.TestCase):
    def test_output_inside_the_application_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "app"
            (root / "scripts").mkdir(parents=True)
            settings = config(MYBLOG_BACKUP_OUTPUT=str(root / "backups"),
                              BLOG_CONTENT_HISTORY_DIR=str(Path(folder) / "history"))
            with patch.object(backup, "runtime", return_value=settings), \
                 patch.object(sys, "argv", ["backup_to_drive.py", "--app-dir", str(root)]):
                with self.assertRaises(ValueError):
                    backup.main()


if __name__ == "__main__":
    unittest.main()
