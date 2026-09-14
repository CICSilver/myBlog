"""Non-secret machine settings shared by WSGI, Flask CLI and maintenance tools."""
import json
import os
from pathlib import Path


def load_runtime(project_root, environ=None):
    environ = os.environ if environ is None else environ
    root = Path(project_root).resolve()
    path = Path(environ.get("BLOG_RUNTIME_CONFIG") or root / "instance/runtime.json")
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("runtime.json must contain an object")
    for key in ("BLOG_ENV", "BLOG_DB_PATH", "BLOG_CONTENT_HISTORY_DIR", "BLOG_MAINTENANCE_LOCK"):
        if environ.get(key):
            data[key] = environ[key]
    data.setdefault("BLOG_ENV", "development")
    data.setdefault("BLOG_DB_PATH", str(root / "db/blog_db.sqlite3"))
    data.setdefault("BLOG_MAINTENANCE_LOCK", str(root / "instance/maintenance.lock"))
    for key in ("BLOG_DB_PATH", "BLOG_CONTENT_HISTORY_DIR", "BLOG_MAINTENANCE_LOCK"):
        if data.get(key):
            candidate = Path(data[key]).expanduser()
            data[key] = str((candidate if candidate.is_absolute() else root / candidate).resolve())
    return data
