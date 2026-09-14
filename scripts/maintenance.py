"""Shared-config status and offline restore, including missing/corrupt databases."""
import argparse
from pathlib import Path
import subprocess
import sys
import os
import tempfile

from deployment_support import health, inspect_database, maintenance_lock, runtime, service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", default=str(Path(__file__).resolve().parents[1]))
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    history = sub.add_parser("history-list")
    history.add_argument("--limit", type=int, default=20)
    restore = sub.add_parser("restore")
    restore.add_argument("snapshot")
    restore.add_argument("--confirm-stop", action="store_true")
    args = parser.parse_args()
    root = Path(args.app_dir).resolve()
    config = runtime(root)
    if args.action == "history-list":
        sys.path.insert(0, str(root))
        from app.content_history import list_history
        for entry in list_history(config["BLOG_CONTENT_HISTORY_DIR"], limit=args.limit):
            print(entry["timestamp"], entry["reason"], entry["path"])
        return
    if args.action == "status":
        health(config)
        print(inspect_database(config["BLOG_DB_PATH"]))
        print("history=" + config["BLOG_CONTENT_HISTORY_DIR"])
        return
    if not args.confirm_stop:
        parser.error("Restore requires --confirm-stop")
    with maintenance_lock(root, config):
        sys.path.insert(0, str(root))
        # Importing app does not create a Flask app or open the database.
        from app.content_history import load_snapshot, restore_snapshot
        if Path(args.snapshot).resolve() == Path(config["BLOG_DB_PATH"]).resolve():
            raise ValueError("Restore source must differ from the live database")
        content, _data = load_snapshot(args.snapshot)
        descriptor, pinned = tempfile.mkstemp(prefix=".restore-source-", dir=root / "instance")
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        active = subprocess.run(["systemctl", "is-active", "--quiet", config["MYBLOG_SERVICE"]]).returncode == 0
        try:
            service("stop", config)
            restore_snapshot(pinned, config["BLOG_DB_PATH"], service_stopped=True, sqlite_target=True)
        finally:
            Path(pinned).unlink(missing_ok=True)
            if active:
                service("start", config)
        if active:
            health(config)
        print("RESTORED; previous DB and journal files retained in quarantine")


if __name__ == "__main__":
    main()
