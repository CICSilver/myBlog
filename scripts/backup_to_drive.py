"""Capture a baseline, store it off-site encrypted, and prune by retention policy.

Ordering is the safety property: nothing uploads until the local bundle verifies,
and nothing is pruned until the uploaded object reads back byte-identical through
the crypt layer. Any failure leaves every existing copy, local and remote, alone.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from deployment_support import atomic_bytes, maintenance_lock, run, runtime, verify_bundle_output

ARCHIVE_KINDS = ("full", "content-history")
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
CHUNK = 1 << 20


def stamp_of(name):
    """baseline-20260919T040632Z-full.tar.gz -> ("20260919T040632Z", "full")"""
    for kind in ARCHIVE_KINDS:
        suffix = "-" + kind + ".tar.gz"
        if name.startswith("baseline-") and name.endswith(suffix):
            return name[len("baseline-"):-len(suffix)], kind
    raise ValueError("Unrecognised recovery archive name: " + name)


def parse_stamp(stamp):
    return datetime.strptime(stamp, STAMP_FORMAT).replace(tzinfo=timezone.utc)


def rclone(config, *args, timeout=3600):
    return run([config["MYBLOG_RCLONE"], *args], timeout=timeout)


def remote_digest(config, remote, timeout=3600):
    """Read the object back through the crypt layer and hash what comes out.

    Crypt over Drive exposes no trustworthy server-side hash, so a real download
    is the only evidence that the encrypt/decrypt round trip is intact.
    """
    process = subprocess.Popen([config["MYBLOG_RCLONE"], "cat", remote],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    digest, size = hashlib.sha256(), 0
    try:
        for chunk in iter(lambda: process.stdout.read(CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
    finally:
        process.stdout.close()
        error = process.stderr.read().decode("utf-8", "replace")
        process.stderr.close()
    if process.wait(timeout=timeout):
        raise RuntimeError("Reading back " + remote + " failed: " + error.strip()[-500:])
    return digest.hexdigest(), size


def capture(root, config, output, fd):
    output.mkdir(parents=True, exist_ok=True)
    os.chmod(output, 0o700)
    # create_recovery_bundle.py takes the same maintenance lock. Hand it this
    # process's descriptor; spawning it plainly would block on a lock we hold.
    env = dict(os.environ, MYBLOG_MAINTENANCE_FD=str(fd))
    text = run([config["MYBLOG_PYTHON"], root / "scripts/create_recovery_bundle.py",
                "--app-dir", root, "--output", output, "--online"],
               env=env, pass_fds=(fd,), timeout=1800)
    if not text.strip().endswith("BASELINE_COMPLETE"):
        raise RuntimeError("Recovery capture did not run to completion")
    return verify_bundle_output(text)


def upload(config, receipts):
    remote_root = config["MYBLOG_BACKUP_REMOTE"].rstrip("/")
    entries = []
    for item in receipts:
        stamp, kind = stamp_of(Path(item["archive"]).name)
        remote = "%s/%s/%s.tar.gz" % (remote_root, stamp, kind)
        rclone(config, "copyto", item["archive"], remote)
        digest, size = remote_digest(config, remote)
        if digest != item["sha256"] or size != item["size"]:
            # Never leave an object that failed verification pretending to be a backup.
            rclone(config, "deletefile", remote, timeout=300)
            raise RuntimeError("Uploaded object did not read back identical: " + remote)
        entries.append({"remote": remote, "filename": kind + ".tar.gz",
                        "size": item["size"], "sha256": item["sha256"]})
    return entries


def retain(stamps, keep_daily, keep_weekly, pinned):
    """The newest keep_daily, the newest of each of the last keep_weekly ISO weeks, and pinned."""
    ordered = sorted(stamps, reverse=True)
    keep = {stamp for stamp in ordered if stamp in pinned}
    keep.update(ordered[:keep_daily])
    weekly = {}
    for stamp in ordered:
        weekly.setdefault(parse_stamp(stamp).isocalendar()[:2], stamp)
    for week in sorted(weekly, reverse=True)[:keep_weekly]:
        keep.add(weekly[week])
    return keep


def remote_stamps(config):
    listing = rclone(config, "lsf", "--dirs-only", config["MYBLOG_BACKUP_REMOTE"].rstrip("/") + "/", timeout=300)
    stamps = []
    for line in listing.splitlines():
        name = line.strip().rstrip("/")
        try:
            parse_stamp(name)
        except ValueError:
            continue
        stamps.append(name)
    return stamps


def prune_remote(config, current):
    stamps = remote_stamps(config)
    keep = retain(stamps, int(config["MYBLOG_BACKUP_KEEP_DAILY"]),
                  int(config["MYBLOG_BACKUP_KEEP_WEEKLY"]), set(config["MYBLOG_BACKUP_PINNED"]))
    keep.add(current)
    if stamps:
        keep.add(max(stamps))
    minimum = int(config["MYBLOG_BACKUP_MIN_REMOTE"])
    removed = []
    for stamp in sorted(set(stamps) - keep):
        if len(stamps) - len(removed) <= minimum:
            break
        rclone(config, "purge", config["MYBLOG_BACKUP_REMOTE"].rstrip("/") + "/" + stamp, timeout=600)
        removed.append(stamp)
    return removed


def prune_local(output, config, current):
    stamps = {stamp_of(path.name)[0] for path in output.glob("baseline-*.tar.gz")}
    keep = set(sorted(stamps, reverse=True)[:int(config["MYBLOG_BACKUP_KEEP_LOCAL"])])
    keep |= stamps & set(config["MYBLOG_BACKUP_PINNED"])
    keep.add(current)
    removed = []
    for stamp in sorted(stamps - keep):
        for path in list(output.glob("baseline-" + stamp + "*")) + [output / ("receipt-" + stamp + ".json")]:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        removed.append(stamp)
    # The bundler leaves its uncompressed staging tree beside each archive.
    for path in output.glob("baseline-*"):
        if path.is_dir():
            shutil.rmtree(path)
    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", default="/home/xyr/myBlog")
    parser.add_argument("--no-prune", action="store_true", help="Upload and verify only; keep every existing copy")
    args = parser.parse_args()
    os.umask(0o077)
    root = Path(args.app_dir).resolve()
    config = runtime(root)
    output = Path(config["MYBLOG_BACKUP_OUTPUT"]).resolve()
    if output.is_relative_to(root) or output.is_relative_to(Path(config["BLOG_CONTENT_HISTORY_DIR"])):
        raise ValueError("Backup output must live outside the application and history directories")
    with maintenance_lock(root, config) as fd:
        receipts = capture(root, config, output, fd)
        stamp = stamp_of(Path(receipts[0]["archive"]).name)[0]
        entries = upload(config, receipts)
        atomic_bytes(output / ("receipt-" + stamp + ".json"), (json.dumps(entries, indent=2) + "\n").encode())
        result = {"stamp": stamp, "remotes": [entry["remote"] for entry in entries],
                  "bytes": sum(entry["size"] for entry in entries)}
        if not args.no_prune:
            result["pruned_remote"] = prune_remote(config, stamp)
            result["pruned_local"] = prune_local(output, config, stamp)
        result["completed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        atomic_bytes(output / "last-success.json", (json.dumps(result, indent=2) + "\n").encode())
        print(json.dumps(result), flush=True)
        print("BACKUP_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
