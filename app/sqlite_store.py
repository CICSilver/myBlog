"""SQLite persistence with lossless document fields for the existing blog API.

TinyDB's Query/Document are value helpers only; no TinyDB storage or query cache
is used. Connections are short-lived, except for an explicit business transaction.
"""

from contextlib import contextmanager, closing
import json
import os
from pathlib import Path
import sqlite3
import threading

from tinydb.table import Document


SCHEMA_VERSION = 1
UNIQUE_FIELDS = {
    "blogs": ("year", "month", "html_title"),
    "diaries": ("entry_date",),
    "workouts": ("entry_date",),
    "body_metrics": ("measured_date",),
    "categories": ("name",),
    "date": ("year", "month"),
    "article_view_excluded_ips": ("ip",),
    "settings": ("key",),
}


def validate_documents(data):
    if not isinstance(data, dict):
        raise ValueError("Expected a database object containing tables")
    for name, rows in data.items():
        if not isinstance(name, str) or not isinstance(rows, dict):
            raise ValueError("Invalid database table")
        for key, row in rows.items():
            if str(int(key)) != str(key) or not 0 < int(key) < 2**63 or not isinstance(row, dict):
                raise ValueError("Invalid document ID or record in " + name)
    return data


def is_sqlite(path):
    with open(path, "rb") as source:
        return source.read(16) == b"SQLite format 3\x00"


def read_documents(path):
    if not is_sqlite(path):
        with open(path, encoding="utf-8") as source:
            return validate_documents(json.load(source))
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.execute("BEGIN")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise ValueError("Unsupported myBlog schema version")
        result = {row[0]: {} for row in connection.execute("SELECT name FROM document_tables ORDER BY rowid")}
        for name, key, body in connection.execute("SELECT table_name, doc_id, body FROM documents ORDER BY seq"):
            result[name][str(key)] = json.loads(body)
    return validate_documents(result)


def backup_sqlite(source, target):
    """Capture committed pages, including WAL, without copying live DB files."""
    if Path(target).exists():
        raise FileExistsError(target)
    uri = Path(source).resolve().as_uri() + "?mode=ro"
    source_db = sqlite3.connect(uri, uri=True, timeout=15)
    target_db = sqlite3.connect(target)
    try:
        source_db.backup(target_db, pages=256, sleep=0.05)
        if target_db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup integrity check failed")
    finally:
        target_db.close()
        source_db.close()
    read_documents(target)


class SQLiteStore:
    def __init__(self, path, create=True):
        self.path = str(Path(path).resolve())
        self.create = create
        self._local = threading.local()
        self._initialized_pid = None
        self._init_lock = threading.Lock()

    def _connect(self):
        if self.create:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
            except FileExistsError:
                pass
        elif not Path(self.path).is_file():
            raise FileNotFoundError("Production database missing: " + self.path)
        connection = sqlite3.connect(Path(self.path).as_uri() + ("?mode=rwc" if self.create else "?mode=rw"), uri=True, timeout=15, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            if self._initialized_pid != os.getpid():
                with self._init_lock:
                    if self._initialized_pid != os.getpid():
                        # Host SQLite 3.40.1 predates the WAL-reset corruption fix.
                        # Rollback journaling keeps transactional durability without WAL.
                        connection.execute("PRAGMA journal_mode=DELETE")
                        connection.execute("BEGIN IMMEDIATE")
                        try:
                            version = connection.execute("PRAGMA user_version").fetchone()[0]
                            if version not in (0, SCHEMA_VERSION):
                                raise ValueError("Unsupported myBlog schema version")
                            if version == 0 and not self.create:
                                raise ValueError("Production database is uninitialized")
                            if version == 0 and connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                                raise ValueError("Refusing to initialize an unrelated SQLite database")
                            connection.execute("CREATE TABLE IF NOT EXISTS document_tables (name TEXT PRIMARY KEY)")
                            connection.execute("""CREATE TABLE IF NOT EXISTS documents (
                                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                                table_name TEXT NOT NULL REFERENCES document_tables(name),
                                doc_id INTEGER NOT NULL CHECK(doc_id > 0),
                                body TEXT NOT NULL CHECK(json_valid(body) AND json_type(body)='object'),
                                UNIQUE(table_name, doc_id))""")
                            for name, fields in UNIQUE_FIELDS.items():
                                expressions = ", ".join("json_extract(body, '$.%s')" % key for key in fields)
                                connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_%s ON documents (%s) WHERE table_name='%s'" % (name, expressions, name))
                            connection.execute("PRAGMA user_version=1")
                            connection.commit()
                        except BaseException:
                            connection.rollback()
                            raise
                        self._initialized_pid = os.getpid()
            return connection
        except BaseException:
            connection.close()
            raise

    @property
    def in_transaction(self):
        return getattr(self._local, "pid", None) == os.getpid() and getattr(self._local, "connection", None) is not None

    @contextmanager
    def connection(self):
        if self.in_transaction:
            yield self._local.connection
        else:
            connection = self._connect()
            try:
                yield connection
            finally:
                connection.close()

    @contextmanager
    def transaction(self):
        if self.in_transaction:
            connection = self._local.connection
            depth = self._local.depth + 1
            self._local.depth = depth
            marker = "nested_%d" % depth
            count = len(self._local.callbacks)
            connection.execute("SAVEPOINT " + marker)
            try:
                yield self
                connection.execute("RELEASE " + marker)
            except BaseException:
                connection.execute("ROLLBACK TO " + marker)
                connection.execute("RELEASE " + marker)
                del self._local.callbacks[count:]
                raise
            finally:
                self._local.depth -= 1
            return
        connection = self._connect()
        callbacks = []
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._local.connection = connection
            self._local.pid = os.getpid()
            self._local.depth = 0
            self._local.callbacks = callbacks
            yield self
            connection.commit()
        except BaseException:
            connection.rollback()
            callbacks.clear()
            raise
        finally:
            self._local.connection = None
            connection.close()
        for callback in callbacks:
            callback()

    def after_commit(self, callback):
        if self.in_transaction:
            self._local.callbacks.append(callback)
        else:
            callback()

    def table(self, name):
        return SQLiteTable(self, name)

    def export(self):
        with self.connection() as connection:
            # One read transaction gives all tables a consistent snapshot.
            own = not self.in_transaction
            if own:
                connection.execute("BEGIN")
            try:
                result = {row[0]: {} for row in connection.execute("SELECT name FROM document_tables ORDER BY rowid")}
                for name, key, body in connection.execute("SELECT table_name, doc_id, body FROM documents ORDER BY seq"):
                    result[name][str(key)] = json.loads(body)
                return result
            finally:
                if own:
                    connection.rollback()

    def replace_all(self, data):
        validate_documents(data)
        with self.transaction():
            connection = self._local.connection
            connection.execute("DELETE FROM documents")
            connection.execute("DELETE FROM document_tables")
            for name, rows in data.items():
                connection.execute("INSERT INTO document_tables(name) VALUES (?)", (name,))
                for key, body in rows.items():
                    self.table(name).insert(Document(body, doc_id=int(key)))

    def close(self):
        if self.in_transaction:
            raise RuntimeError("Cannot close during a business transaction")


class SQLiteTable:
    def __init__(self, store, name):
        self.store = store
        self.name = name

    def all(self):
        with self.store.connection() as connection:
            return [Document(json.loads(body), doc_id=key) for key, body in connection.execute(
                "SELECT doc_id, body FROM documents WHERE table_name=? ORDER BY seq", (self.name,))]

    def search(self, condition):
        return [row for row in self.all() if condition(row)]

    def get(self, condition=None, doc_id=None):
        if doc_id is not None:
            with self.store.connection() as connection:
                result = connection.execute("SELECT body FROM documents WHERE table_name=? AND doc_id=?", (self.name, doc_id)).fetchone()
                return None if result is None else Document(json.loads(result[0]), doc_id=doc_id)
        return next((row for row in self.all() if (row.doc_id == doc_id if doc_id is not None else condition(row))), None)

    def insert(self, document):
        with self.store.transaction():
            connection = self.store._local.connection
            connection.execute("INSERT OR IGNORE INTO document_tables(name) VALUES (?)", (self.name,))
            key = getattr(document, "doc_id", None)
            if key is None:
                key = connection.execute("SELECT coalesce(max(doc_id),0)+1 FROM documents WHERE table_name=?", (self.name,)).fetchone()[0]
            if self.get(doc_id=key) is not None:
                raise ValueError("Document with ID %s already exists" % key)
            connection.execute("INSERT INTO documents(table_name,doc_id,body) VALUES (?,?,?)", (self.name, key, json.dumps(document, ensure_ascii=False)))
            return key

    def update(self, fields, condition=None, doc_ids=None):
        with self.store.transaction():
            rows = [row for row in self.all() if (row.doc_id in doc_ids if doc_ids is not None else condition(row))]
            for row in rows:
                if callable(fields):
                    fields(row)
                else:
                    row.update(fields)
                self.store._local.connection.execute("UPDATE documents SET body=? WHERE table_name=? AND doc_id=?", (json.dumps(row, ensure_ascii=False), self.name, row.doc_id))
            return [row.doc_id for row in rows]

    def remove(self, condition=None, doc_ids=None):
        with self.store.transaction():
            rows = [row for row in self.all() if (row.doc_id in doc_ids if doc_ids is not None else condition(row))]
            self.store._local.connection.executemany("DELETE FROM documents WHERE table_name=? AND doc_id=?", [(self.name, row.doc_id) for row in rows])
            return [row.doc_id for row in rows]

    def truncate(self):
        with self.store.transaction():
            self.store._local.connection.execute("DELETE FROM documents WHERE table_name=?", (self.name,))

    def __len__(self):
        return len(self.all())
