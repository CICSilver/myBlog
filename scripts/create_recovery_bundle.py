"""Create a stopped-service recovery baseline on the myBlog host (no upload)."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
from datetime import datetime, timezone


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
    parser.add_argument("--stop-service", action="store_true")
    args = parser.parse_args()
    if not args.stop_service:
        parser.error("Explicit --stop-service is required")
    os.umask(0o077)
    app = Path("/home/xyr/myBlog")
    history = Path("/root/.local/share/SilverBlog/history")
    output = Path(args.output).resolve()
    if output.is_relative_to(app) or output.is_relative_to(history):
        parser.error("Output must be outside live data")
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".baseline.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if command("systemctl", "is-active", "myblog.service").strip() != "active":
            raise RuntimeError("Live service must be active before capture")
        if command("systemctl", "show", "myblog.service", "-p", "KillSignal", "--value").strip() != "15":
            raise RuntimeError("Graceful SIGTERM shutdown must be configured first")
        name = datetime.now(timezone.utc).strftime("baseline-%Y%m%dT%H%M%SZ")
        stage = output / name
        stage.mkdir()
        full = stage / "full"
        full.mkdir()
        runtime = full / "runtime"
        runtime.mkdir()
        (runtime / "requirements.freeze.txt").write_text(command("/home/venv/bin/python", "-m", "pip", "freeze"))
        (runtime / "python-version.txt").write_text(command("/home/venv/bin/python", "--version"))
        (runtime / "myblog.service.effective.txt").write_text(command("systemctl", "cat", "myblog.service"))
        (runtime / "git-head.txt").write_text(command("git", "-C", str(app), "rev-parse", "HEAD"))
        (runtime / "git-status.txt").write_text(command("git", "-C", str(app), "status", "--short"))
        for source, target in [
            (Path("/etc/systemd/system/myblog.service"), runtime / "myblog.service"),
            (Path("/home/xyr/update_myblog.sh"), runtime / "update_myblog.sh"),
            (Path("/etc/caddy/Caddyfile"), runtime / "Caddyfile"),
        ]:
            shutil.copy2(source, target)
        override = Path("/etc/systemd/system/myblog.service.d")
        if override.exists():
            shutil.copytree(override, runtime / "myblog.service.d")
        started = time.monotonic()
        try:
            command("systemctl", "stop", "myblog.service", timeout=100)
            shutil.copytree(app, full / "app", ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
            shutil.copytree(history, stage / "content-history")
        finally:
            command("systemctl", "start", "myblog.service", timeout=100)
        ready = False
        for _ in range(20):
            result = subprocess.run(["curl", "--noproxy", "*", "-fsS", "--max-time", "2", "-o", "/dev/null", "http://127.0.0.1:8900/"], capture_output=True)
            if result.returncode == 0:
                ready = True
                break
            time.sleep(0.5)
        if not ready:
            raise RuntimeError("Service started but HTTP health check failed; do not upload")
        print("SERVICE_HEALTHY capture_and_restart_seconds=%.2f" % (time.monotonic() - started), flush=True)
        database = json.loads((full / "app/db/blog_db.json").read_text(encoding="utf-8"))
        if not isinstance(database, dict) or not all(isinstance(table, dict) for table in database.values()):
            raise RuntimeError("Invalid TinyDB baseline")
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
