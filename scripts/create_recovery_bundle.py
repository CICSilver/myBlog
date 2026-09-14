"""Create a recovery baseline; SQLite supports --online without stopping the site."""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
from datetime import datetime, timezone
from deployment_support import maintenance_lock, runtime as load_runtime_config


def command(*args, timeout=120):
    return subprocess.check_output(args, timeout=timeout, text=True)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inventory(root):
    return {
        str(path.relative_to(root)): {"size": path.stat().st_size, "sha256": sha256(path)}
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--app-dir", default="/home/xyr/myBlog")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--stop-service", action="store_true")
    mode.add_argument("--online", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    app = Path(args.app_dir).resolve()
    config = load_runtime_config(app)
    history = Path(config["BLOG_CONTENT_HISTORY_DIR"])
    database_path = Path(config["BLOG_DB_PATH"])
    service_name = config["MYBLOG_SERVICE"]
    if not database_path.resolve().is_relative_to(app):
        parser.error("External database location requires an explicit bundle mapping")
    with database_path.open("rb") as source:
        sqlite_format = source.read(16) == b"SQLite format 3\x00"
    if args.online and not sqlite_format:
        parser.error("Online backup requires SQLite")
    storage = None
    if sqlite_format:
        spec = importlib.util.spec_from_file_location("backup_storage", app / "app/sqlite_store.py")
        storage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(storage)
    output = Path(args.output).resolve()
    if output.is_relative_to(app) or output.is_relative_to(history):
        parser.error("Output must be outside live data")
    output.mkdir(parents=True, exist_ok=True)
    with maintenance_lock(app, config):
        if command("systemctl", "is-active", service_name).strip() != "active":
            raise RuntimeError("Live service must be active before capture")
        if args.stop_service and command("systemctl", "show", service_name, "-p", "KillSignal", "--value").strip() != "15":
            raise RuntimeError("Graceful SIGTERM shutdown must be configured first")
        name = datetime.now(timezone.utc).strftime("baseline-%Y%m%dT%H%M%SZ")
        stage = output / name
        stage.mkdir()
        full = stage / "full"
        full.mkdir()
        runtime = full / "runtime"
        runtime.mkdir()
        (runtime / "requirements.freeze.txt").write_text(command(config["MYBLOG_PYTHON"], "-m", "pip", "freeze"))
        (runtime / "python-version.txt").write_text(command(config["MYBLOG_PYTHON"], "--version"))
        (runtime / "myblog.service.effective.txt").write_text(command("systemctl", "cat", service_name))
        (runtime / "git-head.txt").write_text(command("git", "-C", str(app), "rev-parse", "HEAD"))
        (runtime / "git-status.txt").write_text(command("git", "-C", str(app), "status", "--short"))
        for source, target in [
            (Path("/etc/systemd/system") / service_name, runtime / "myblog.service"),
            (app.parent / "update_myblog.sh", runtime / "update_myblog.sh"),
            (Path("/etc/caddy/Caddyfile"), runtime / "Caddyfile"),
        ]:
            shutil.copy2(source, target)
        override = Path("/etc/systemd/system") / (service_name + ".d")
        if override.exists():
            shutil.copytree(override, runtime / "myblog.service.d")
        started = time.monotonic()
        try:
            if args.stop_service:
                command("systemctl", "stop", service_name, timeout=100)
            excluded = [".git", "__pycache__", "*.pyc"]
            if sqlite_format:
                excluded += [database_path.name, database_path.name + "-wal", database_path.name + "-shm", database_path.name + "-journal"]
                target_database = full / "app" / database_path.relative_to(app)
                target_database.parent.mkdir(parents=True, exist_ok=True)
                storage.backup_sqlite(database_path, target_database)
            shutil.copytree(app, full / "app", ignore=shutil.ignore_patterns(*excluded), dirs_exist_ok=True)
            with (history / ".history.lock").open("a") as history_lock:
                fcntl.flock(history_lock, fcntl.LOCK_EX)
                shutil.copytree(history, stage / "content-history")
        finally:
            if args.stop_service:
                command("systemctl", "start", service_name, timeout=100)
        ready = False
        for _ in range(20):
            result = subprocess.run(["curl", "--noproxy", "*", "-fsS", "--max-time", "2", "-o", "/dev/null", config["MYBLOG_HEALTH_URL"]], capture_output=True)
            if result.returncode == 0:
                ready = True
                break
            time.sleep(0.5)
        if not ready:
            raise RuntimeError("Service started but HTTP health check failed; do not upload")
        print("SERVICE_HEALTHY mode=%s capture_seconds=%.2f" % ("online" if args.online else "stopped", time.monotonic() - started), flush=True)
        captured_db = full / "app" / database_path.relative_to(app)
        database = storage.read_documents(captured_db) if sqlite_format else json.loads(captured_db.read_text(encoding="utf-8"))
        if not isinstance(database, dict) or not all(isinstance(table, dict) for table in database.values()):
            raise RuntimeError("Invalid database baseline")
        (runtime / "database.json").write_text(json.dumps({"format": "sqlite" if sqlite_format else "json", "path": str(database_path.relative_to(app)), "tables": {name: len(rows) for name, rows in database.items()}}))
        shutil.copy2(Path(__file__).with_name("RECOVERY.md"), full / "RECOVERY.md")
        for folder, suffix in [(full, "full"), (stage / "content-history", "content-history")]:
            manifest = inventory(folder)
            (folder / "BACKUP-MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            target = output / (name + "-" + suffix + ".tar.gz")
            temporary = target.with_suffix(target.suffix + ".tmp")
            with tarfile.open(temporary, "w:gz") as archive:
                archive.add(folder, arcname=suffix)
            os.replace(temporary, target)
            print(json.dumps({"archive": str(target), "size": target.stat().st_size, "sha256": sha256(target), "files": len(manifest)}), flush=True)
        print("BASELINE_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
