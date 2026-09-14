# Deployment and maintenance

## One shared configuration

`instance/runtime.json` is local-only, mode 600, and is preserved by Git updates.
It contains non-secret database/history/maintenance-lock paths, service name,
Python runtime, and deployment directories. Keep passwords and API keys in
`instance/config.py`, not this file. Environment overrides remain available for
isolated tests. WSGI, Flask CLI, backup and maintenance all read runtime.json.

Production startup requires an existing, valid SQLite database. A missing,
empty or incompatible database fails startup instead of producing an empty
website. Development and the explicit migration tool can initialize databases.

## Install or rebuild a host

Clone the repository into the intended app directory. Restore a validated
SQLite backup, or stop the old service and explicitly run `migrate_sqlite.py`
against its JSON source. The updater never migrates or restores data itself.
Create a virtualenv and install `scripts/deployment-requirements.txt`, then run:

    /home/venv/bin/python scripts/install_runtime.py \
      --app-dir /home/xyr/myBlog \
      --database /home/xyr/myBlog/db/blog_db.sqlite3 \
      --history /var/lib/myblog/history \
      --python /home/venv/bin/python \
      --lock /var/lock/myblog-maintenance.lock

The installer refuses a missing/invalid database. It is idempotent, updates only
its managed service drop-in and launchers, and does not restart or enable the
service. Review the resulting unit, then start/enable it deliberately. Existing
unmanaged unit settings and private rclone credentials are preserved.

`/home/xyr/update_myblog.sh` and the backup Python launchers resolve scripts in
the checkout rather than keeping independent code copies. Each successful
update reconciles these launchers; failed updates restore the previous runtime.
The original one-off `deploy_sqlite.py` is retired and exits without changes.

## Normal update

    /home/xyr/update_myblog.sh --check
    /home/xyr/update_myblog.sh

Actual updates run as transient systemd units and log to journald so an SSH
disconnect does not interrupt a stopped-service operation. `--check` stays in
the foreground and does not create a unit. Optional MYBLOG_PROXY applies only
to the updater process and its Git/pip children, not to the blog service.

The updater only accepts a clean tracked tree, the intended branch, a
fast-forward commit, no untracked-file collisions, and a compatible
`scripts/deployment.json`. It refuses tracked DB/private runtime files,
symlinks/submodules, and targets that lack the maintenance contract. It never
uses `git reset --hard`. `--check` fetches and validates but does not install,
change the checkout, or stop services; full dependency/test preflight occurs
only during an actual update.

Before stopping the site, an update builds a separate virtualenv, installs and
checks dependencies, validates both recovery archives, runs candidate tests,
and renders the candidate homepage against a disposable database copy.
This requires pip 22.3 or newer in the current virtualenv. New environments
use `--without-pip` plus pip's `--python` support, avoiding a dependency on the
host distribution's optional ensurepip package.
The updater defaults to the HTTPS PyPI index instead of inheriting a host's
possibly proxy-incompatible intranet mirror. Override MYBLOG_PIP_INDEX_URL in
runtime.json when needed; global pip settings are not modified.
Immediately before switching it captures another consistent database snapshot.
Git then fast-forwards, the service selects the new virtualenv, and health checks
validate both SQLite integrity and HTTP. No schema migration is automatic.

On activation failure, only deployment-owned code and runtime configuration
are rolled back. The database is NEVER restored automatically, so new writes
are preserved. Unexpected schema changes or externally edited code block
automatic rollback rather than silently losing data. Failure evidence remains
in MYBLOG_UPDATE_ROOT. Keep the active and previous virtualenvs and recovery
archives; no automatic cleanup is configured. Update failures should be
investigated before retrying, especially if health cannot be restored.

## Previously hand-deployed files

After committing and pushing a verified hand deployment, use:

    /home/xyr/update_myblog.sh --adopt-deployed

This aligns the server's Git index/HEAD ONLY when every target file matches the
deployment byte-for-byte, no removed tracked file remains, and the index has no
staged edits. It refuses mismatches and never overwrites working files. This
is not a way to ignore a dirty tree. Ordinary updates do not adopt silently.

## Backup and restore

Update, full backup and restore share BLOG_MAINTENANCE_LOCK. Backup child
processes inherit the parent's OS lock explicitly; stale locks are not stolen.
Flask CLI history commands use the same history path as the service.

    /home/venv/bin/python scripts/maintenance.py status
    /home/venv/bin/python scripts/maintenance.py history-list
    /home/venv/bin/python scripts/maintenance.py restore SNAPSHOT --confirm-stop

Use `maintenance.py` for missing/corrupt-DB recovery: it does not start the Flask
app, validates the source, stops the service under the maintenance lock,
quarantines current DB/journals, restores, and restarts if previously active.
The low-level Flask `history-restore --service-stopped` also rejects an active
production service; it is not the recovery entry point for a missing database.

Full backup remains manually invoked with `create_recovery_bundle.py --online`
and explicit output directory, followed by encrypted upload and download
verification. No timer or automatic cloud-retention policy is enabled here.

## Verification boundaries

Tests cover missing production DB, shared settings, installer idempotence,
dirty-tree/collision/contract rejection, preflight failure without downtime,
partial checkout rollback, and retaining post-start writes on rollback.
Fresh-host DNS/TLS and network availability still require operator validation.
