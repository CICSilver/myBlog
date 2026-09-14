"""Fast-forward deployment with preflight, verified backup, and code-only rollback."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

from deployment_support import atomic_bytes, contract, database_backup, health, inspect_database, maintenance_lock, run, runtime, service
from install_runtime import install


def git(root, *args):
    return run(["git", "-C", root, *args], timeout=int(os.environ.get("GIT_TIMEOUT_SECONDS", "120")))


def target_files(root, revision):
    if any(line.startswith("120000 ") or line.startswith("160000 ") for line in git(root, "ls-tree", "-r", revision).splitlines()):
        raise ValueError("Deployment does not accept symlinks or submodules")
    files = git(root, "ls-tree", "-r", "--name-only", revision).splitlines()
    for name in files:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or name.startswith("db/") or (name.startswith("instance/") and name != "instance/config.example.py") or name == ".env":
            raise ValueError("Release tracks protected runtime data: " + name)
    return files


def ensure_clean(root):
    try:
        git(root, "diff", "--quiet")
        git(root, "diff", "--cached", "--quiet")
    except RuntimeError as error:
        raise RuntimeError("Tracked files or index are dirty; commit or explicitly reconcile before updating") from error


def adopt_deployed(root, target, run_dir):
    """Align Git metadata only when every deployed target file matches byte-for-byte."""
    git(root, "diff", "--cached", "--quiet")
    names = target_files(root, target)
    for name in names:
        path = root / name
        blob = subprocess.check_output(["git", "-C", str(root), "show", target + ":" + name])
        if not path.is_file() or path.is_symlink() or path.read_bytes() != blob:
            raise ValueError("Cannot adopt: deployed file differs from target: " + name)
    for name in set(git(root, "ls-files").splitlines()) - set(names):
        if (root / name).exists():
            raise ValueError("Cannot adopt: obsolete tracked file still exists: " + name)
    old = git(root, "rev-parse", "HEAD").strip()
    git(root, "merge-base", "--is-ancestor", old, target)
    shutil.copy2(root / ".git/index", run_dir / "index.before-adopt")
    atomic_bytes(run_dir / "head.before-adopt", old.encode())
    git(root, "read-tree", target)
    try:
        git(root, "update-ref", "-m", "Adopt verified deployed files", "HEAD", target, old)
    except BaseException:
        shutil.copy2(run_dir / "index.before-adopt", root / ".git/index")
        raise


def verify_bundle_output(output):
    receipts = []
    for line in output.splitlines():
        if not line.startswith('{"archive":'):
            continue
        item = json.loads(line)
        path = Path(item["archive"])
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
        receipts.append(item)
    if len(receipts) != 2:
        raise ValueError("Both full and history recovery archives are required")
    return receipts


def rollback(root, old, target, changed, old_config, quarantine=None):
    current = git(root, "rev-parse", "HEAD").strip()
    if current not in (old, target):
        raise ValueError("Git HEAD changed externally; refusing rollback")
    old_names = set(target_files(root, old))
    new_names = set(target_files(root, target))
    dirty = set(git(root, "diff", "--name-only").splitlines()) | set(git(root, "diff", "--cached", "--name-only").splitlines())
    if dirty - set(changed):
        raise ValueError("Unrelated working tree changes found during rollback")
    for name in changed:
        expected = []
        for revision, names in [(old, old_names), (target, new_names)]:
            expected.append(subprocess.check_output(["git", "-C", str(root), "show", revision + ":" + name]) if name in names else None)
        path = root / name
        actual = path.read_bytes() if path.is_file() else None
        if path.is_symlink() or actual not in expected:
            raise ValueError("File changed outside the deployment: " + name)
    version = inspect_database(old_config["BLOG_DB_PATH"])["schema_version"]
    # The updater never changes schema; an unexpected change stops automatic rollback.
    old_contract = json.loads(git(root, "show", old + ":scripts/deployment.json"))
    if version not in old_contract["writable_schema_versions"]:
        raise ValueError("Current DB is incompatible with rollback release")
    indexed = set(git(root, "ls-files").splitlines())
    restore_names = sorted(set(changed) & (old_names | indexed))
    if restore_names:
        git(root, "restore", "--source=" + old, "--staged", "--worktree", "--", *restore_names)
    for name in set(changed) - old_names - indexed:
        path = root / name
        if path.exists():
            destination = Path(quarantine) / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, destination)
    git(root, "update-ref", "-m", "Rollback failed deployment (code only)", "HEAD", old, current)
    install(root, old_config)


def prepare_candidate(root, candidate, config, run_dir, fd):
    # A new environment is prepared without changing the running environment.
    venv = run_dir / "venv"
    # Debian may omit ensurepip even when the running virtualenv has pip.
    run([config["MYBLOG_PYTHON"], "-m", "venv", "--without-pip", venv], timeout=120)
    python = venv / "bin/python"
    pip_version = run([config["MYBLOG_PYTHON"], "-c", "import importlib.metadata; print(importlib.metadata.version('pip'))"]).strip()
    pip = subprocess.run([config["MYBLOG_PYTHON"], "-m", "pip", "--python", str(python), "install", "--index-url", config.get("MYBLOG_PIP_INDEX_URL", "https://pypi.org/simple"), "pip==" + pip_version, "-r", str(candidate / "scripts/deployment-requirements.txt")], capture_output=True, text=True, timeout=600)
    atomic_bytes(run_dir / "dependencies.log", (pip.stdout + pip.stderr).encode())
    if pip.returncode:
        raise RuntimeError("Candidate dependency installation failed; live environment unchanged")
    run([python, "-m", "pip", "check"])
    # Backup, update and restore share the same inherited OS lock.
    env = dict(os.environ, MYBLOG_MAINTENANCE_FD=str(fd))
    backup_output = run([config["MYBLOG_PYTHON"], root / "scripts/create_recovery_bundle.py", "--app-dir", root, "--output", run_dir / "backup", "--online"], env=env, pass_fds=(fd,), timeout=300)
    receipts = verify_bundle_output(backup_output)
    atomic_bytes(run_dir / "backup-receipt.json", json.dumps(receipts, indent=2).encode())
    stage_db = run_dir / "preflight.sqlite3"
    database_backup(config["BLOG_DB_PATH"], stage_db)
    (candidate / "instance").mkdir(exist_ok=True)
    if (root / "instance/config.py").exists():
        shutil.copy2(root / "instance/config.py", candidate / "instance/config.py")
    stage_env = dict(os.environ, BLOG_DB_PATH=str(stage_db), BLOG_CONTENT_HISTORY_DIR=str(run_dir / "test-history"), BLOG_MAINTENANCE_LOCK=str(run_dir / "test-maintenance.lock"), BLOG_ENV="development", BLOG_SECRET_KEY="isolated-update-preflight")
    stage_env.pop("MYBLOG_MAINTENANCE_FD", None)
    stage_env.pop("BLOG_RUNTIME_CONFIG", None)
    test = subprocess.run([str(python), "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=candidate, env=stage_env, capture_output=True, text=True, timeout=180)
    atomic_bytes(run_dir / "tests.log", (test.stdout + test.stderr).encode())
    if test.returncode:
        raise RuntimeError("Candidate tests failed; service was not stopped")
    stage_env["BLOG_ENV"] = "production"
    run([python, "-c", "from app import create_app; a=create_app(); a.config['TESTING']=True; assert a.test_client().get('/').status_code==200"], cwd=candidate, env=stage_env)
    return python


def deploy(root, config, target, run_dir, fd, check_only=False):
    ensure_clean(root)
    old = git(root, "rev-parse", "HEAD").strip()
    git(root, "merge-base", "--is-ancestor", old, target)
    version = inspect_database(config["BLOG_DB_PATH"])["schema_version"]
    names = target_files(root, target)
    untracked = set(git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    if untracked.intersection(names):
        raise ValueError("Target would overwrite untracked files")
    candidate = run_dir / "candidate"
    candidate.mkdir()
    data = subprocess.check_output(["git", "-C", str(root), "archive", target])
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(candidate, filter="data")
    contract(candidate, version)
    contract(root, version)
    if check_only:
        health(config)
        print("CHECK_OK: clean tree, fast-forward, protected paths, schema compatibility and health")
        return
    if old == target:
        install(root, config)
        health(config)
        print("ALREADY_CURRENT: runtime launchers reconciled")
        return
    python = prepare_candidate(root, candidate, config, run_dir, fd)
    changed = git(root, "diff", "--name-only", old, target).splitlines()
    old_config = dict(config)
    new_config = dict(config, MYBLOG_PYTHON=str(python))
    stopped = False
    switched = False
    try:
        # Recheck immediately before activation. Preserve the latest DB, not just preflight state.
        ensure_clean(root)
        stopped = True
        service("stop", config)
        database_backup(config["BLOG_DB_PATH"], run_dir / "database-at-switch.sqlite3")
        atomic_bytes(run_dir / "runtime-before.json", json.dumps(old_config, indent=2).encode())
        switched = True
        git(root, "merge", "--ff-only", "--no-edit", target)
        install(root, new_config)
        service("start", new_config)
        for attempt in range(10):
            try:
                health(new_config)
                break
            except Exception:
                if attempt == 9:
                    raise
                time.sleep(1)
        atomic_bytes(run_dir / "result.json", json.dumps({"status": "complete", "old": old, "new": target, "database": inspect_database(config["BLOG_DB_PATH"])}).encode())
        print("UPDATE_COMPLETE " + target)
    except BaseException:
        if stopped:
            service("stop", config)
            if switched:
                # Preserve post-start writes, and roll back code/runtime only.
                database_backup(config["BLOG_DB_PATH"], run_dir / "database-at-failure.sqlite3")
                rollback(root, old, target, changed, old_config, quarantine=run_dir / "failed-checkout")
            service("start", old_config)
            health(old_config)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", default="/home/xyr/myBlog")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--check", action="store_true", help="Fetch and validate only; no install or service changes")
    parser.add_argument("--adopt-deployed", action="store_true", help="Align Git metadata only after byte-for-byte verification")
    args = parser.parse_args()
    if args.check and args.adopt_deployed:
        parser.error("--check cannot modify Git metadata")
    os.umask(0o077)
    root = Path(args.app_dir).resolve()
    if not (root / ".git").is_dir():
        raise RuntimeError("Clone and bootstrap the repository first; updater does not replace arbitrary directories")
    config = runtime(root)
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    if config.get("MYBLOG_PROXY"):
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ[name] = config["MYBLOG_PROXY"]
    with maintenance_lock(root, config) as fd:
        if git(root, "symbolic-ref", "HEAD").strip() != "refs/heads/" + args.branch:
            raise ValueError("Checkout branch does not match requested branch")
        directory = Path(config["MYBLOG_UPDATE_ROOT"]).resolve()
        if directory.is_relative_to(root):
            raise ValueError("Update directory must be outside the application")
        directory.mkdir(parents=True, exist_ok=True)
        run_dir = directory / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        run_dir.mkdir()
        for attempt in range(3):
            try:
                git(root, "fetch", "--no-tags", "origin", args.branch)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        target = git(root, "rev-parse", "FETCH_HEAD^{commit}").strip()
        try:
            if args.adopt_deployed:
                adopt_deployed(root, target, run_dir)
            deploy(root, config, target, run_dir, fd, check_only=args.check)
        except BaseException as error:
            atomic_bytes(run_dir / "error.log", (str(error) + "\n" + getattr(error, "details", "")).encode())
            print("UPDATE_FAILED; recovery and diagnostics retained at " + str(run_dir))
            raise


if __name__ == "__main__":
    main()
