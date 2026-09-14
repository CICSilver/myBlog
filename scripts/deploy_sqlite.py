"""One-time, host-local cutover. Run under systemd-run, after candidate tests."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

LIVE = Path("/home/xyr/myBlog")
CANDIDATE = Path("/opt/myblog-sqlite-candidate-523952d")
HISTORY = Path("/var/lib/myblog/history")
DROPIN = Path("/etc/systemd/system/myblog.service.d/95-sqlite.conf")
FILES = [
    "app/__init__.py", "app/database.py", "app/content_history.py",
    "app/sqlite_store.py", "app/file_lock.py", "scripts/migrate_sqlite.py",
    "scripts/create_recovery_bundle.py", "scripts/verify_recovery_bundle.py",
    "scripts/RECOVERY.md", "scripts/SQLITE-MIGRATION.md",
    "tests/test_article_views.py", "tests/test_blog_html_title.py",
    "tests/test_diary_database.py", "tests/test_content_history.py",
    "tests/test_sqlite_migration.py",
]


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, timeout=120, **kwargs)


def main():
    os.umask(0o077)
    target = LIVE / "db/blog_db.sqlite3"
    if target.exists() or DROPIN.exists() or HISTORY.exists():
        raise RuntimeError("Cutover destination already exists; manual review required")
    for name in FILES:
        if not (CANDIDATE / name).is_file():
            raise RuntimeError("Candidate file missing: " + name)
    if run("systemctl", "is-active", "myblog.service").strip() != "active":
        raise RuntimeError("Expected an active service")
    backup = Path("/var/backups/myblog-sqlite-cutover") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup.mkdir(parents=True, mode=0o700)
    old_history = Path("/root/.local/share/SilverBlog/history")
    touched = []
    start_attempted = False
    stopped = False
    started = time.monotonic()
    try:
        run("systemctl", "stop", "myblog.service")
        stopped = True
        shutil.copytree(LIVE, backup / "app", ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        shutil.copytree(old_history, backup / "history")
        shutil.copytree(DROPIN.parent, backup / "service-dropins")
        shutil.copy2("/etc/systemd/system/myblog.service", backup / "myblog.service")
        result = run("/home/venv/bin/python", str(CANDIDATE / "scripts/migrate_sqlite.py"), str(LIVE / "db/blog_db.json"), str(target), "--repair-derived", "--apply")
        (backup / "migration-report.json").write_text(result)
        for name in FILES:
            destination = LIVE / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".sqlite-deploy.tmp")
            shutil.copy2(CANDIDATE / name, temporary)
            touched.append(name)
            os.replace(temporary, destination)
        shutil.copytree(old_history, HISTORY)
        manifest = HISTORY / "manifest.json"
        entries = json.loads(manifest.read_text())
        for entry in entries:
            entry["path"] = Path(entry["path"]).name
            if not (HISTORY / entry["path"]).is_file():
                raise RuntimeError("Historical snapshot missing")
        manifest.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        DROPIN.write_text("[Service]\nEnvironment=BLOG_DB_PATH=/home/xyr/myBlog/db/blog_db.sqlite3\nEnvironment=BLOG_CONTENT_HISTORY_DIR=/var/lib/myblog/history\n")
        run("systemctl", "daemon-reload")
        check = "from app import create_app; a=create_app(); a.config['TESTING']=True; c=a.test_client(); assert c.get('/').status_code==200; print('NEW_APP_PRESTART_OK')"
        env = dict(os.environ, BLOG_DB_PATH=str(target), BLOG_CONTENT_HISTORY_DIR=str(HISTORY))
        print(run("/home/venv/bin/python", "-c", check, cwd=LIVE, env=env), flush=True)
        start_attempted = True
        run("systemctl", "start", "myblog.service")
        for _ in range(20):
            result_health = subprocess.run(["curl", "--noproxy", "*", "-fsS", "--max-time", "2", "-o", "/dev/null", "http://127.0.0.1:8900/"], capture_output=True)
            if result_health.returncode == 0:
                print("CUTOVER_OK downtime_seconds=%.2f recovery=%s" % (time.monotonic() - started, backup), flush=True)
                print(result, flush=True)
                return
            time.sleep(0.5)
        raise RuntimeError("Post-start health check failed; new DB retained for diagnosis")
    except BaseException:
        if stopped and not start_attempted:
            failed = backup / "failed-candidate"
            failed.mkdir(exist_ok=True)
            for name in touched:
                current = LIVE / name
                saved = failed / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                if current.exists():
                    os.replace(current, saved)
                old = backup / "app" / name
                if old.exists():
                    shutil.copy2(old, current)
            for suffix in ("", "-wal", "-shm", "-journal"):
                path = Path(str(target) + suffix)
                if path.exists():
                    os.replace(path, failed / path.name)
            if DROPIN.exists():
                os.replace(DROPIN, failed / DROPIN.name)
            if HISTORY.exists():
                shutil.move(str(HISTORY), str(failed / "history"))
            run("systemctl", "daemon-reload")
        # Never silently roll back SQLite after it could have accepted new writes.
        run("systemctl", "start", "myblog.service")
        raise


if __name__ == "__main__":
    main()
