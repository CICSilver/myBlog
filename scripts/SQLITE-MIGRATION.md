# SQLite migration and backups

## Storage contract

The default database is `db/blog_db.sqlite3`. Set `BLOG_DB_PATH` explicitly
for deployments and tests. A legacy JSON file is never auto-imported or
overwritten during app startup. Migration is an explicit offline operation.

SQLite owns persistence, transactions, IDs, unique constraints, and crash
recovery. The `documents` table preserves original per-table document IDs,
field values, unknown fields, and insertion order. Partial SQL unique indexes
enforce article URLs, diary dates, category names, archive months, excluded IPs,
and settings keys. `devices` and other legacy tables are retained.

TinyDB remains a dependency ONLY for the existing `Query` predicates and
`Document` value type. There is no TinyDB database, storage handle, or query
cache. Queries use fresh SQLite reads; predicate matching remains in Python
for compatibility with the existing small dataset. This is not a full SQL
query optimization or a rewrite of every business model.

Each outer write operation uses BEGIN IMMEDIATE and commits all table changes
together. Nested writes use savepoints. Connections are closed after each
operation; no connection is shared between Gunicorn workers. DELETE rollback
journaling and FULL synchronous writes are enabled, with a 15-second busy
timeout. The host's SQLite 3.40.1 predates the WAL-reset corruption fix, so WAL
is deliberately not enabled in production. Backup/restore also accepts WAL
sources through SQLite's backup API; never copy live journal sidecars.

## Offline migration

1. Create and verify a full pre-migration recovery baseline.
2. Rehearse with a copied JSON source:

       python scripts/migrate_sqlite.py source.json rehearsal.sqlite3 --repair-derived

3. Stop the service, preserve the exact live code, configuration, JSON, and
   history directory. Run against the now-stable source:

       python scripts/migrate_sqlite.py db/blog_db.json db/blog_db.sqlite3 --repair-derived --apply

4. The command refuses an existing target, checks constraints and compares
   every migrated field. `--repair-derived` adds only missing category/month
   records and recalculates their counts from articles. Other tables and
   fields are not modified. Duplicates or invalid records abort the import.
5. Switch code and BLOG_DB_PATH, restart, and verify reads before allowing
   normal traffic. Keep the old JSON and the recovery baseline.

Rollback to JSON is safe only before accepting new SQLite writes. Once users
write to SQLite, stop and preserve the new DB with the backup API before
planning rollback; never silently discard these writes.

## History and recovery

Automatic pre/post history remains portable JSON exports. Pre-state is captured
inside the business transaction; post-state is captured there and published
only after commit. Rolled-back operations do not publish post-state. Repeated
identical consecutive states are deduplicated. An OS-backed lock serializes
manifest changes and pruning across processes.

`flask --app run history-snapshot` uses SQLite's backup API and creates a
validated `.sqlite3` snapshot including committed WAL pages. The history list
supports both old JSON and new SQLite snapshots. Entries use relative paths;
old absolute paths have a filename fallback after a directory move.

Stop ALL app processes before running:

    flask --app run history-restore SNAPSHOT --service-stopped

The selected source and recorded checksum are validated first. A new SQLite
file is built and validated before replacing anything. The previous database
and WAL/SHM sidecars are moved to a uniquely named quarantine directory,
including when the previous database is corrupt. The restore command does
not prune away its selected target. Restart the app after restoration.
The flag is an operator assertion, not an automatic service-stop mechanism.

## Full encrypted backup

Run `create_recovery_bundle.py` with the application's virtualenv Python.
`--online` is available only for SQLite and uses the backup API, never a live
copy of the main DB/WAL files. JSON still requires `--stop-service`.
Database format/path/counts are recorded in `runtime/database.json`.
The verifier accepts historical JSON bundles and new SQLite bundles.

Online capture assumes successful uploads are immutable and old media remain
available; this is the current application behavior. Do not deploy code,
change runtime config, or garbage-collect uploaded media during capture.
For a strict maintenance baseline, use `--stop-service` instead.

Upload archives only through `myblog_crypt:`. Download/decrypt, compare archive
and file hashes, and run `verify_recovery_bundle.py` before considering a
backup verified. The crypt keys and Google tokens remain outside the archive.
No scheduler or automatic cloud-retention policy is introduced by migration.
