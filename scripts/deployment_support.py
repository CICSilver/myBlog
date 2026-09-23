"""Shared deployment primitives. Never restore a database as a code rollback."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tarfile
import tempfile


def load_module(root, name):
    spec = importlib.util.spec_from_file_location("maintenance_" + name, Path(root) / "app" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runtime(root):
    result = load_module(root, "runtime_config").load_runtime(root)
    result.setdefault("MYBLOG_SERVICE", "myblog.service")
    result.setdefault("MYBLOG_PYTHON", "/home/venv/bin/python")
    result.setdefault("MYBLOG_HEALTH_URL", "http://127.0.0.1:8900/")
    result.setdefault("MYBLOG_UPDATE_ROOT", "/var/lib/myblog/updates")
    result.setdefault("MYBLOG_TOOLS_DIR", "/opt/myblog-backup")
    result.setdefault("MYBLOG_BIND", "0.0.0.0:8900")
    result.setdefault("MYBLOG_WORKERS", 2)
    result.setdefault("MYBLOG_PIP_INDEX_URL", "https://pypi.org/simple")
    result.setdefault("MYBLOG_RCLONE", "/opt/myblog-backup/run-rclone")
    result.setdefault("MYBLOG_BACKUP_OUTPUT", "/var/backups/myblog")
    result.setdefault("MYBLOG_BACKUP_REMOTE", "myblog_crypt:baselines")
    result.setdefault("MYBLOG_BACKUP_KEEP_DAILY", 7)
    result.setdefault("MYBLOG_BACKUP_KEEP_WEEKLY", 4)
    result.setdefault("MYBLOG_BACKUP_KEEP_LOCAL", 2)
    # Never pruned: the reviewed pre-migration and post-migration baselines.
    result.setdefault("MYBLOG_BACKUP_PINNED", ["20260914T064414Z", "20260914T071041Z", "20260914T084554Z"])
    result.setdefault("MYBLOG_BACKUP_MIN_REMOTE", 3)
    return result


def atomic_bytes(path, content, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".install-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def inspect_database(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError("Database missing: " + str(path))
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=15)) as connection:
        connection.execute("BEGIN")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Database integrity check failed")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        rows = connection.execute("SELECT table_name,doc_id,body FROM documents ORDER BY seq").fetchall()
        names = [row[0] for row in connection.execute("SELECT name FROM document_tables ORDER BY rowid")]
        digest = hashlib.sha256(json.dumps([names, rows], ensure_ascii=False).encode()).hexdigest()
        return {"schema_version": version, "rows": len(rows), "logical_sha256": digest}


def database_backup(source, target):
    target = Path(target)
    if target.exists():
        raise FileExistsError(target)
    with closing(sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True, timeout=15)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst, pages=256, sleep=0.05)
    return inspect_database(target)


def verify_bundle_archives(items):
    """Check each archive's own digest and every member against its manifest."""
    for item in items:
        path = Path(item["archive"])
        if path.stat().st_size != item["size"]:
            raise ValueError("Recovery archive size mismatch: " + path.name)
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise ValueError("Recovery archive checksum mismatch")
        with tarfile.open(path) as archive:
            manifests = [member for member in archive.getmembers() if member.name.endswith("/BACKUP-MANIFEST.json")]
            if len(manifests) != 1:
                raise ValueError("Recovery manifest missing")
            manifest = json.load(archive.extractfile(manifests[0]))
            prefix = manifests[0].name.rsplit("/", 1)[0]
            for name, entry in manifest.items():
                stream = archive.extractfile(prefix + "/" + name.replace("\\", "/"))
                if stream is None or hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]:
                    raise ValueError("Recovery member checksum mismatch")
    if len(items) != 2:
        raise ValueError("Both full and history recovery archives are required")
    return items


def verify_bundle_output(output):
    """Verify the archives named on create_recovery_bundle.py's stdout."""
    return verify_bundle_archives([json.loads(line) for line in output.splitlines() if line.startswith('{"archive":')])


def contract(root, version):
    path = Path(root) / "scripts/deployment.json"
    if not path.is_file():
        raise ValueError("Target lacks the deployment compatibility contract")
    data = json.loads(path.read_text())
    if data.get("maintenance_api") != 1 or version not in data.get("readable_schema_versions", []) or version not in data.get("writable_schema_versions", []):
        raise ValueError("Release is incompatible with the current database")
    if data.get("database_migration") != "explicit-offline-only":
        raise ValueError("Automatic schema changes are not allowed by this updater")
    for name in ["app/runtime_config.py", "scripts/install_runtime.py", "scripts/update_myblog.py", "scripts/update_myblog.sh", "scripts/deployment_support.py", "scripts/create_recovery_bundle.py", "scripts/maintenance.py", "scripts/deployment-requirements.txt"]:
        if not (Path(root) / name).is_file():
            raise ValueError("Release lacks maintenance component: " + name)
    return data


def run(args, cwd=None, env=None, timeout=120, pass_fds=()):
    result = subprocess.run(list(map(str, args)), cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, pass_fds=pass_fds)
    if result.returncode:
        # Keep details in the protected run directory; do not print secrets from child output.
        error = RuntimeError("Command failed (%d): %s" % (result.returncode, Path(str(args[0])).name))
        error.details = result.stdout + result.stderr
        raise error
    return result.stdout


def service(action, config):
    return run(["systemctl", action, config["MYBLOG_SERVICE"]])


def health(config):
    inspect_database(config["BLOG_DB_PATH"])
    run(["curl", "--noproxy", "*", "-fsS", "--max-time", "5", "-o", "/dev/null", config["MYBLOG_HEALTH_URL"]], timeout=10)


def maintenance_lock(root, config):
    path = Path(config["BLOG_MAINTENANCE_LOCK"])
    path.parent.mkdir(parents=True, exist_ok=True)
    return load_module(root, "file_lock").file_lock(str(path))
