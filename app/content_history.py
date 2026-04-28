import hashlib
import json
import os
import re
from datetime import datetime


APP_HISTORY_NAME = "SilverBlog"
DEFAULT_MAX_SNAPSHOTS = 200
MANIFEST_NAME = "manifest.json"


def default_history_dir():
    base_dir = (
        os.environ.get("BLOG_CONTENT_HISTORY_DIR")
        or os.environ.get("LOCALAPPDATA")
        or os.environ.get("APPDATA")
    )
    if base_dir:
        return os.path.join(base_dir, APP_HISTORY_NAME, "history")
    return os.path.join(os.path.expanduser("~"), ".local", "share", APP_HISTORY_NAME, "history")


def snapshot_content_db(db_path, reason, history_dir=None, max_snapshots=DEFAULT_MAX_SNAPSHOTS):
    if not db_path or not os.path.exists(db_path):
        return None

    history_dir = history_dir or default_history_dir()
    os.makedirs(history_dir, exist_ok=True)

    with open(db_path, "rb") as source:
        content = source.read()

    # Fail fast on a corrupt source file instead of preserving an unusable snapshot.
    json.loads(content.decode("utf-8"))

    digest = hashlib.sha256(content).hexdigest()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    safe_reason = _safe_reason(reason)
    filename = "blog_db-{0}-{1}-{2}.json".format(timestamp, safe_reason, digest[:12])
    snapshot_path = os.path.join(history_dir, filename)
    temp_path = snapshot_path + ".tmp"

    with open(temp_path, "wb") as target:
        target.write(content)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temp_path, snapshot_path)

    entry = {
        "timestamp": timestamp,
        "reason": reason,
        "sha256": digest,
        "size": len(content),
        "path": snapshot_path,
    }
    _append_manifest_entry(history_dir, entry)
    prune_history(history_dir, max_snapshots=max_snapshots)
    return entry


def list_history(history_dir=None, limit=None):
    history_dir = history_dir or default_history_dir()
    manifest_path = os.path.join(history_dir, MANIFEST_NAME)
    if not os.path.exists(manifest_path):
        return []

    with open(manifest_path, "r", encoding="utf-8") as manifest:
        entries = json.load(manifest)

    entries = [entry for entry in entries if os.path.exists(entry.get("path", ""))]
    entries.sort(key=lambda entry: entry.get("timestamp", ""), reverse=True)
    if limit is not None:
        entries = entries[:limit]
    return entries


def restore_snapshot(snapshot_path, target_db_path):
    if not os.path.exists(snapshot_path):
        raise FileNotFoundError(snapshot_path)

    with open(snapshot_path, "rb") as source:
        content = source.read()
    json.loads(content.decode("utf-8"))

    target_dir = os.path.dirname(target_db_path)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    temp_path = target_db_path + ".restore.tmp"
    with open(temp_path, "wb") as target:
        target.write(content)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temp_path, target_db_path)


def prune_history(history_dir=None, max_snapshots=DEFAULT_MAX_SNAPSHOTS):
    history_dir = history_dir or default_history_dir()
    entries = list_history(history_dir)
    if max_snapshots is None or max_snapshots <= 0 or len(entries) <= max_snapshots:
        return

    keep = entries[:max_snapshots]
    remove = entries[max_snapshots:]
    for entry in remove:
        path = entry.get("path")
        if path and os.path.exists(path):
            os.remove(path)
    _write_manifest(history_dir, keep)


def _safe_reason(reason):
    reason = str(reason or "manual")
    reason = re.sub(r"[^A-Za-z0-9_.-]+", "-", reason).strip("-")
    return reason[:40] or "manual"


def _append_manifest_entry(history_dir, entry):
    entries = list_history(history_dir)
    entries.insert(0, entry)
    _write_manifest(history_dir, entries)


def _write_manifest(history_dir, entries):
    os.makedirs(history_dir, exist_ok=True)
    manifest_path = os.path.join(history_dir, MANIFEST_NAME)
    temp_path = manifest_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as manifest:
        json.dump(entries, manifest, ensure_ascii=False, indent=2)
        manifest.write("\n")
        manifest.flush()
        os.fsync(manifest.fileno())
    os.replace(temp_path, manifest_path)
