import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import uuid
from datetime import datetime

from app.file_lock import file_lock
from app.sqlite_store import SQLiteStore, backup_sqlite, is_sqlite, read_documents

APP_HISTORY_NAME = "SilverBlog"
DEFAULT_MAX_SNAPSHOTS = 200
MANIFEST_NAME = "manifest.json"


def default_history_dir():
    override = os.environ.get("BLOG_CONTENT_HISTORY_DIR")
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    return os.path.join(base, APP_HISTORY_NAME, "history") if base else os.path.join(os.path.expanduser("~"), ".local", "share", APP_HISTORY_NAME, "history")


def snapshot_content_db(db_path, reason, history_dir=None, max_snapshots=DEFAULT_MAX_SNAPSHOTS, source=None):
    if not db_path or not os.path.exists(db_path):
        return None
    history_dir = history_dir or default_history_dir()
    os.makedirs(history_dir, exist_ok=True)
    if source is not None:
        # Capture transaction-local state now, publish post-state only after commit.
        content = json.dumps(source.export(), ensure_ascii=False).encode("utf-8")
        if str(reason).startswith("post-") and source.in_transaction:
            def publish():
                try:
                    _save_content(content, ".json", reason, history_dir, max_snapshots)
                except Exception:
                    logging.getLogger(__name__).exception("Committed content history snapshot failed")
            source.after_commit(publish)
            return None
        return _save_content(content, ".json", reason, history_dir, max_snapshots)
    if is_sqlite(db_path):
        temporary = os.path.join(history_dir, uuid.uuid4().hex + ".sqlite3.tmp")
        try:
            backup_sqlite(db_path, temporary)
            content = Path(temporary).read_bytes()
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
        extension = ".sqlite3"
    else:
        read_documents(db_path)
        content = Path(db_path).read_bytes()
        extension = ".json"
    return _save_content(content, extension, reason, history_dir, max_snapshots)


def _save_content(content, extension, reason, history_dir, maximum):
    digest = hashlib.sha256(content).hexdigest()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    filename = "blog_db-{}-{}-{}{}".format(timestamp, _safe_reason(reason), digest[:12], extension)
    path = os.path.join(history_dir, filename)
    with file_lock(os.path.join(history_dir, ".history.lock")):
        entries = list_history(history_dir)
        if entries and entries[0].get("sha256") == digest:
            return entries[0]
        temporary = path + ".tmp"
        with open(temporary, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        entry = {"timestamp": timestamp, "reason": reason, "sha256": digest, "size": len(content), "path": os.path.abspath(path)}
        entries.insert(0, entry)
        _write_manifest(history_dir, entries)
        _prune_history(history_dir, maximum)
        return entry


def list_history(history_dir=None, limit=None):
    history_dir = history_dir or default_history_dir()
    manifest = Path(history_dir) / MANIFEST_NAME
    if not manifest.exists():
        return []
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    result = []
    for entry in entries:
        path = Path(entry.get("path", ""))
        if not path.is_absolute():
            path = Path(history_dir) / path
        if not path.is_file():
            path = Path(history_dir) / path.name
        if path.is_file():
            result.append({**entry, "path": str(path.resolve())})
    result.sort(key=lambda entry: entry.get("timestamp", ""), reverse=True)
    return result if limit is None else result[:limit]


def restore_snapshot(snapshot_path, target_db_path, service_stopped=False, sqlite_target=None):
    # Pin the source before any pruning; quarantine even a corrupt current DB.
    source_bytes = Path(snapshot_path).read_bytes()
    manifest = Path(snapshot_path).parent / MANIFEST_NAME
    if manifest.exists():
        entry = next((item for item in list_history(str(manifest.parent)) if Path(item["path"]).resolve() == Path(snapshot_path).resolve()), None)
        if entry and hashlib.sha256(source_bytes).hexdigest() != entry.get("sha256"):
            raise ValueError("Snapshot checksum mismatch")
    data = read_documents(snapshot_path)
    target = Path(target_db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if sqlite_target is None:
        sqlite_target = target.suffix in (".sqlite3", ".sqlite", ".db") or (target.exists() and is_sqlite(target))
    if sqlite_target and not service_stopped:
        raise ValueError("Stop all application processes before restoring SQLite")
    temporary = target.with_name(target.name + ".restore-" + uuid.uuid4().hex)
    try:
        if sqlite_target:
            SQLiteStore(temporary).replace_all(data)
            read_documents(temporary)
        else:
            with temporary.open("wb") as stream:
                stream.write(source_bytes if not is_sqlite(snapshot_path) else json.dumps(data, ensure_ascii=False).encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
        if target.exists() or any(Path(str(target) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
            quarantine = target.parent / (target.name + ".pre-restore-" + uuid.uuid4().hex)
            quarantine.mkdir(mode=0o700)
            for suffix in ("", "-wal", "-shm", "-journal"):
                old = Path(str(target) + suffix)
                if old.exists():
                    shutil.move(str(old), str(quarantine / old.name))
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def prune_history(history_dir=None, max_snapshots=DEFAULT_MAX_SNAPSHOTS):
    history_dir = history_dir or default_history_dir()
    os.makedirs(history_dir, exist_ok=True)
    with file_lock(os.path.join(history_dir, ".history.lock")):
        _prune_history(history_dir, max_snapshots)


def _prune_history(history_dir, maximum):
    entries = list_history(history_dir)
    if maximum is None or maximum <= 0 or len(entries) <= maximum:
        return
    keep, remove = entries[:maximum], entries[maximum:]
    _write_manifest(history_dir, keep)
    for entry in remove:
        path = Path(entry["path"]).resolve()
        if path.is_relative_to(Path(history_dir).resolve()) and path.is_file():
            path.unlink()


def _safe_reason(reason):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(reason or "manual")).strip("-")[:40] or "manual"


def _write_manifest(history_dir, entries):
    manifest = Path(history_dir) / MANIFEST_NAME
    rows = [{**entry, "path": os.path.relpath(entry["path"], history_dir)} for entry in entries]
    temporary = manifest.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(rows, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, manifest)
