import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import nullcontext

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import update_myblog as updater
from deployment_support import inspect_database, contract
from install_runtime import install
import install_runtime as installer
from app.runtime_config import load_runtime
from app.sqlite_store import SQLiteStore


class RuntimeTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Checks the Linux virtualenv symlink used by production")
    def test_installer_preserves_virtualenv_python_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            interpreter = root / "venv-python"
            interpreter.symlink_to(sys.executable)
            config = {"BLOG_CONTENT_HISTORY_DIR": str(root / "history")}
            with patch.object(sys, "argv", ["install_runtime.py", "--app-dir", str(root), "--python", str(interpreter)]), patch.object(installer, "runtime", return_value=config), patch.object(installer, "maintenance_lock", return_value=nullcontext()), patch.object(installer, "install") as apply:
                installer.main()
            self.assertEqual(apply.call_args.args[1]["MYBLOG_PYTHON"], str(interpreter))
    @unittest.skipIf(os.name == "nt", "Inherited descriptors are used by Linux maintenance subprocesses")
    def test_inherited_maintenance_lock_does_not_deadlock(self):
        from app.file_lock import file_lock
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "maintenance.lock")
            with file_lock(path) as fd:
                env = dict(os.environ, MYBLOG_MAINTENANCE_FD=str(fd))
                code = "from app.file_lock import file_lock; import sys;\nwith file_lock(sys.argv[1]): print('LOCK_OK')"
                result = subprocess.run([sys.executable, "-c", code, path], cwd=ROOT, env=env, pass_fds=(fd,), capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("LOCK_OK", result.stdout)
    def test_shared_paths_and_environment_override(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "instance").mkdir()
            (root / "instance/runtime.json").write_text(json.dumps({"BLOG_ENV": "production", "BLOG_DB_PATH": "db/site.sqlite3", "BLOG_CONTENT_HISTORY_DIR": "history"}))
            cli = load_runtime(root, {})
            service = load_runtime(root, {"BLOG_ENV": "production"})
            self.assertEqual(cli, service)
            self.assertEqual(cli["BLOG_CONTENT_HISTORY_DIR"], str(root / "history"))
            override = load_runtime(root, {"BLOG_DB_PATH": str(root / "override.sqlite3"), "BLOG_SECRET_KEY": "not-persisted"})
            self.assertEqual(override["BLOG_DB_PATH"], str(root / "override.sqlite3"))
            self.assertNotIn("BLOG_SECRET_KEY", override)

    def test_missing_production_database_never_creates_an_empty_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "missing.sqlite3"
            env = dict(os.environ, BLOG_ENV="production", BLOG_DB_PATH=str(path), BLOG_SECRET_KEY="test-only")
            result = subprocess.run([sys.executable, "-c", "from app import create_app; create_app()"], cwd=ROOT, env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(path.exists())
            store = SQLiteStore(path, create=False)
            with self.assertRaises(FileNotFoundError):
                store.export()
            self.assertFalse(path.exists())

    def test_empty_production_file_is_not_initialized(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "empty.sqlite3"
            path.touch()
            with self.assertRaises(ValueError):
                SQLiteStore(path, create=False).export()
            connection = sqlite3.connect(path)
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])
            connection.close()

    def test_installer_is_idempotent_and_launchers_follow_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "app"
            root.mkdir()
            database = root / "db/site.sqlite3"
            SQLiteStore(database).export()
            config = {"BLOG_ENV": "production", "BLOG_DB_PATH": str(database), "BLOG_CONTENT_HISTORY_DIR": str(root / "history"), "MYBLOG_PYTHON": sys.executable, "MYBLOG_SERVICE": "myblog.service", "MYBLOG_TOOLS_DIR": str(Path(folder) / "tools"), "MYBLOG_WORKERS": 2, "MYBLOG_BIND": "127.0.0.1:8900"}
            systemd = Path(folder) / "systemd"
            install(root, config, systemd_dir=systemd, reload=False)
            first = (systemd / "myblog.service.d/99-myblog-runtime.conf").read_bytes()
            self.assertNotIn(b'WorkingDirectory="', first)
            install(root, config, systemd_dir=systemd, reload=False)
            self.assertEqual(first, (systemd / "myblog.service.d/99-myblog-runtime.conf").read_bytes())
            self.assertIn("scripts/update_myblog.sh", (root.parent / "update_myblog.sh").read_text().replace("\\", "/"))
            wrapper = (Path(config["MYBLOG_TOOLS_DIR"]) / "create_recovery_bundle.py").read_text()
            self.assertIn("os.execv", wrapper)
            self.assertIn("instance/runtime.json", wrapper)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.g("init", "-b", "main")
        self.g("config", "user.name", "Deployment Test")
        self.g("config", "user.email", "test@example.invalid")
        self.g("config", "core.autocrlf", "false")
        self.write("scripts/deployment.json", json.dumps({"maintenance_api": 1, "readable_schema_versions": [1], "writable_schema_versions": [1], "database_migration": "explicit-offline-only"}))
        for name in ["app/runtime_config.py", "scripts/install_runtime.py", "scripts/update_myblog.py", "scripts/update_myblog.sh", "scripts/deployment_support.py", "scripts/create_recovery_bundle.py", "scripts/maintenance.py", "scripts/deployment-requirements.txt"]:
            self.write(name, "# fixture\n")
        self.write("application.txt", "old\n")
        self.old = self.commit("old")
        self.write("application.txt", "new\n")
        self.write("added.txt", "new file\n")
        self.new = self.commit("new")
        self.g("switch", "-c", "deployed", self.old)
        self.database = self.base / "site.sqlite3"
        self.store = SQLiteStore(self.database)
        self.store.table("devices").insert({"value": "before"})
        self.config = {"BLOG_DB_PATH": str(self.database), "MYBLOG_PYTHON": sys.executable, "MYBLOG_SERVICE": "test.service", "MYBLOG_HEALTH_URL": "http://127.0.0.1:1/"}
        self.run_dir = self.base / "run"
        self.run_dir.mkdir()
        self.events = []

    def tearDown(self):
        # Windows Git may mark object files read-only.
        self.assertEqual(self.base.resolve(), Path(self.temp.name).resolve())
        self.assertTrue(self.base.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()))
        def writable(function, path, _exc):
            os.chmod(path, 0o700)
            function(path)
        shutil.rmtree(self.base, onerror=writable)
        self.temp.cleanup()

    def g(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True, stderr=subprocess.DEVNULL).strip()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit(self, message):
        self.g("add", ".")
        self.g("commit", "-qm", message)
        return self.g("rev-parse", "HEAD")

    def prepare(self, *args):
        self.events.append("prepared")
        return Path(sys.executable)

    def service(self, action, config):
        self.events.append(action)

    def test_success_is_fast_forward_and_does_not_restore_database(self):
        before = inspect_database(self.database)
        with patch.object(updater, "prepare_candidate", self.prepare), patch.object(updater, "install"), patch.object(updater, "health"), patch.object(updater, "service", self.service):
            updater.deploy(self.root, self.config, self.new, self.run_dir, 0)
        self.assertEqual(self.events, ["prepared", "stop", "start"])
        self.assertEqual(self.g("rev-parse", "HEAD"), self.new)
        self.assertEqual(inspect_database(self.database), before)
        self.assertTrue((self.run_dir / "database-at-switch.sqlite3").is_file())

    def test_preflight_failure_never_stops_service(self):
        with patch.object(updater, "prepare_candidate", side_effect=RuntimeError("dependency or backup failure")), patch.object(updater, "service", self.service):
            with self.assertRaises(RuntimeError):
                updater.deploy(self.root, self.config, self.new, self.run_dir, 0)
        self.assertEqual(self.events, [])
        self.assertEqual(self.g("rev-parse", "HEAD"), self.old)

    def test_dependency_preflight_does_not_require_system_ensurepip(self):
        calls = []
        def command(args, **kwargs):
            calls.append(args)
            return "25.1\n" if "-c" in args else ""
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="dependency download failed")
        with patch.object(updater, "run", command), patch.object(updater.subprocess, "run", return_value=failed) as pip:
            with self.assertRaisesRegex(RuntimeError, "dependency installation failed"):
                updater.prepare_candidate(self.root, self.root, self.config, self.run_dir, 0)
        self.assertIn("--without-pip", calls[0])
        self.assertIn("--python", pip.call_args.args[0])
        self.assertEqual(pip.call_args.args[0][0], self.config["MYBLOG_PYTHON"])
        self.assertEqual(self.events, [])

    def test_dirty_tree_is_not_overwritten(self):
        self.write("application.txt", "user edit\n")
        with self.assertRaisesRegex(RuntimeError, "dirty"):
            updater.deploy(self.root, self.config, self.new, self.run_dir, 0)
        self.assertEqual((self.root / "application.txt").read_text(), "user edit\n")

    def test_untracked_collision_is_rejected_before_stop(self):
        self.write("added.txt", "user file\n")
        with self.assertRaisesRegex(ValueError, "untracked"):
            updater.deploy(self.root, self.config, self.new, self.run_dir, 0)
        self.assertEqual((self.root / "added.txt").read_text(), "user file\n")

    def test_incompatible_contract_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "incompatible"):
            contract(self.root, 2)

    def test_failed_new_release_rolls_back_code_but_keeps_post_start_writes(self):
        def start(action, config):
            self.events.append(action)
            if action == "start" and self.g("rev-parse", "HEAD") == self.new:
                self.store.table("devices").insert({"value": "after-start"})
        def health(config):
            if self.g("rev-parse", "HEAD") == self.new:
                raise RuntimeError("bad release")
        with patch.object(updater, "prepare_candidate", self.prepare), patch.object(updater, "install"), patch.object(updater, "health", health), patch.object(updater, "service", start), patch.object(updater.time, "sleep"):
            with self.assertRaises(RuntimeError):
                updater.deploy(self.root, self.config, self.new, self.run_dir, 0)
        self.assertEqual(self.g("rev-parse", "HEAD"), self.old)
        self.assertEqual((self.root / "application.txt").read_text(), "old\n")
        self.assertEqual(len(self.store.table("devices").all()), 2)
        self.assertTrue((self.run_dir / "database-at-failure.sqlite3").exists())

    def test_check_mode_makes_no_service_or_worktree_changes(self):
        with patch.object(updater, "health"), patch.object(updater, "service", self.service):
            updater.deploy(self.root, self.config, self.new, self.run_dir, 0, check_only=True)
        self.assertEqual(self.events, [])
        self.assertEqual(self.g("rev-parse", "HEAD"), self.old)

    def test_partial_checkout_failure_is_recovered_without_database_rollback(self):
        original_git = updater.git
        def fail_merge(root, *args):
            if args[0] == "merge":
                self.write("application.txt", "new\n")
                self.write("added.txt", "new file\n")
                raise RuntimeError("checkout failed before HEAD moved")
            return original_git(root, *args)
        with patch.object(updater, "git", fail_merge), patch.object(updater, "prepare_candidate", self.prepare), patch.object(updater, "install"), patch.object(updater, "health"), patch.object(updater, "service", self.service):
            with self.assertRaises(RuntimeError):
                updater.deploy(self.root, self.config, self.new, self.run_dir, 0)
        self.assertEqual(self.g("rev-parse", "HEAD"), self.old)
        self.assertEqual((self.root / "application.txt").read_text(), "old\n")
        self.assertFalse((self.root / "added.txt").exists())
        self.assertTrue((self.run_dir / "failed-checkout/added.txt").exists())

    def test_adoption_requires_exact_deployed_files(self):
        with self.assertRaisesRegex(ValueError, "differs"):
            updater.adopt_deployed(self.root, self.new, self.run_dir)
        self.write("application.txt", "new\n")
        self.write("added.txt", "new file\n")
        updater.adopt_deployed(self.root, self.new, self.run_dir)
        self.assertEqual(self.g("rev-parse", "HEAD"), self.new)
        self.assertEqual(self.g("status", "--short"), "")


if __name__ == "__main__":
    unittest.main()
