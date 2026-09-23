# myBlog Recovery Baseline

This baseline contains private site data and configuration. Keep extracted
copies in restricted directories. Never publish these files or commit them.

## Download and Verify

1. Use the offline recovery kit on the owner's Windows computer. It contains
   the rclone configuration and crypt keys. These keys are NOT in this archive.
   The kit was created and independently verified on 2026-09-19: a baseline was
   listed, downloaded, decrypted and passed `verify_recovery_bundle.py` using
   the kit alone, on a machine other than the server. Recreate and re-verify it
   whenever the crypt parameters, Google client or account change.
2. Download through `myblog_crypt:` with rclone; this decrypts the archive.
   If OAuth has expired or been revoked, reauthorize the same Google client
   and account while preserving the crypt password, salt, and remote path.
3. Compare the archive SHA-256 with the receipt in the offline kit. Extract
   into a new, empty directory, never directly over a running installation.
4. Verify every file against `BACKUP-MANIFEST.json` before restoring.

## Rebuild a Host

The `full/app` tree is the actual deployed working tree, including untracked
application files and runtime data, not merely an export of a Git commit.
`runtime/git-head.txt` and `git-status.txt` describe its provenance.

1. Provision a compatible Linux host and Python version (see runtime files).
   Create a new virtual environment and install the recorded dependencies.
   Package downloads require network access; this is not an offline OS image.
2. Restore `app` to the chosen application directory. Read `runtime/database.json`
   when present to identify the active SQLite or legacy JSON database. Keep `db`, `instance`,
   and all uploads together. Protect `instance/config.py` and do not print it.
3. Review and adapt the service unit, drop-ins, paths, and Caddyfile from
   `runtime` before enabling services. Point DNS at the replacement host.
   TLS certificates can be reissued; old certificate private keys are excluded.
   Re-run `scripts/install_runtime.py` with the replacement host's Python and
   data paths. Do not retain a previous host's update-run virtualenv path from
   `instance/runtime.json`. See `scripts/DEPLOYMENT.md` for the bootstrap steps.
4. Start only after restoring data. Validate the homepage, article pages,
   diaries, and uploaded images before exposing the replacement to users.
5. Configure the backup client and network proxy separately using the offline
   kit. This archive intentionally excludes Google OAuth and crypt credentials,
   SSH keys, and host-wide proxy credentials.

## Historical Snapshots

The separate content-history archive preserves the existing JSON snapshots.
Old manifests may contain absolute source-machine paths. The SQLite-era reader
supports filename fallback and mixed JSON/SQLite snapshots. For SQLite restore,
stop all app processes and pass `history-restore --service-stopped`. The old
database and WAL/SHM files are quarantined before the validated replacement.
For a missing or corrupt database use `scripts/maintenance.py restore
SNAPSHOT --confirm-stop`; the ordinary Flask app deliberately refuses an
invalid production database. Maintenance can also list history independently.

## Isolated Verification

Use a separate database path and upload directories. Override production
secrets and disable outbound metadata requests. Verify file hashes and JSON
table counts before using a Flask test client to render pages. A successful
isolated test is not proof of new-host DNS, TLS, or systemd configuration.

## Retention and Known Limits

`backup_to_drive.py`, run daily by `myblog-backup.timer`, captures, uploads,
verifies by reading each object back, and then prunes. Retention keeps the
newest few days, one baseline per recent ISO week, and a pinned set that is
never pruned; the newest baseline is never removed and pruning is skipped
entirely whenever a run fails. `DEPLOYMENT.md` records the exact policy.
The 2026-09-14 baselines are pinned. Legacy baselines preserve the original data;
post-migration SQLite baselines include the reviewed derived-category repair.
Read the database descriptor and migration report to distinguish them.
Disk copies and backup failures must never be treated as a
reason to silently discard live data.
