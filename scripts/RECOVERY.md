# myBlog Recovery Baseline

This baseline contains private site data and configuration. Keep extracted
copies in restricted directories. Never publish these files or commit them.

## Download and Verify

1. Use the offline recovery kit on the owner's Windows computer. It contains
   the rclone configuration and crypt keys. These keys are NOT in this archive.
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
2. Restore `app` to the chosen application directory. Keep `db`, `instance`,
   and all uploads together. Protect `instance/config.py` and do not print it.
3. Review and adapt the service unit, drop-ins, paths, and Caddyfile from
   `runtime` before enabling services. Point DNS at the replacement host.
   TLS certificates can be reissued; old certificate private keys are excluded.
4. Start only after restoring data. Validate the homepage, article pages,
   diaries, and uploaded images before exposing the replacement to users.
5. Configure the backup client and network proxy separately using the offline
   kit. This archive intentionally excludes Google OAuth and crypt credentials,
   SSH keys, and host-wide proxy credentials.

## Historical Snapshots

The separate content-history archive preserves the existing JSON snapshots.
Its old manifest contains absolute source-machine paths. On a new machine,
rebuild those paths or use verified snapshot files directly. Do not run the
legacy history-restore command against a running service or a corrupt database.

## Isolated Verification

Use a separate database path and upload directories. Override production
secrets and disable outbound metadata requests. Verify file hashes and JSON
table counts before using a Flask test client to render pages. A successful
isolated test is not proof of new-host DNS, TLS, or systemd configuration.

## Retention and Known Limits

This is a manually created, pinned pre-migration baseline. No scheduled backup,
automatic pruning, SQLite migration, or repair of existing data is performed.
In particular, the known missing category relation is preserved for a separate
reviewed repair. Disk copies and backup failures must never be treated as a
reason to silently discard live data.
