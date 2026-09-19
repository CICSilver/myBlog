"""Idempotently install shared non-secret settings and repository-backed launchers."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from deployment_support import atomic_bytes, inspect_database, maintenance_lock, runtime


def render_service(root, config):
    python = Path(config["MYBLOG_PYTHON"])
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
    return ("[Service]\nWorkingDirectory=" + str(root).replace('%', '%%') + "\n"
            "Environment=BLOG_ENV=production\n"
            "UnsetEnvironment=BLOG_DB_PATH BLOG_CONTENT_HISTORY_DIR BLOG_RUNTIME_CONFIG\n"
            "ExecStart=\nExecStart=" + quote(python) + " -m gunicorn --workers " + str(int(config["MYBLOG_WORKERS"])) +
            " --bind " + quote(config["MYBLOG_BIND"]) + " --access-logfile - --error-logfile - run:app\n"
            "KillSignal=SIGTERM\nKillMode=mixed\nTimeoutStopSec=90s\n")


def render_backup_units(root, config):
    """A daily off-site backup, timed after the 04:00 diary day boundary so the
    captured day is already closed. Written but never enabled automatically."""
    command = str(Path(config["MYBLOG_TOOLS_DIR"]) / "backup_to_drive.py").replace('%', '%%')
    service = ("[Unit]\nDescription=myBlog encrypted off-site backup\n"
               "After=network-online.target " + config["MYBLOG_SERVICE"] + "\n"
               "Wants=network-online.target\n\n"
               "[Service]\nType=oneshot\n"
               "ExecStart=" + command + " --app-dir " + str(root).replace('%', '%%') + "\n"
               "Nice=10\nIOSchedulingClass=idle\nTimeoutStartSec=3600\n")
    timer = ("[Unit]\nDescription=Daily myBlog encrypted off-site backup\n\n"
             "[Timer]\nOnCalendar=*-*-* 04:30:00\nPersistent=true\n"
             "RandomizedDelaySec=900\nAccuracySec=1min\n\n"
             "[Install]\nWantedBy=timers.target\n")
    return service, timer


def install(root, config, systemd_dir=Path("/etc/systemd/system"), launcher=None, reload=True):
    root = Path(root).resolve()
    inspect_database(config["BLOG_DB_PATH"])
    if not Path(config["MYBLOG_PYTHON"]).is_file():
        raise FileNotFoundError("Configured Python is missing")
    if reload:
        subprocess.run([config["MYBLOG_PYTHON"], "-c", "import gunicorn, sqlite3"], check=True, capture_output=True)
    settings = root / "instance/runtime.json"
    previous_settings = settings.read_bytes() if settings.exists() else None
    atomic_bytes(root / "instance/runtime.json", (json.dumps(config, indent=2) + "\n").encode())
    service_file = Path(systemd_dir) / config["MYBLOG_SERVICE"]
    if not service_file.exists():
        atomic_bytes(service_file, b"[Unit]\nDescription=myBlog\nAfter=network-online.target\n[Service]\nType=simple\nRestart=on-failure\nRestartSec=3\n[Install]\nWantedBy=multi-user.target\n", 0o644)
    dropin = Path(str(service_file) + ".d") / "99-myblog-runtime.conf"
    previous_dropin = dropin.read_bytes() if dropin.exists() else None
    atomic_bytes(dropin, render_service(root, config).encode(), 0o644)
    if reload:
        try:
            subprocess.run(["systemd-analyze", "verify", "--man=no", str(service_file)], check=True, capture_output=True, timeout=30)
        except BaseException:
            if previous_dropin is None:
                dropin.unlink()
            else:
                atomic_bytes(dropin, previous_dropin, 0o644)
            if previous_settings is None:
                settings.unlink()
            else:
                atomic_bytes(settings, previous_settings)
            raise
    # These wrappers resolve their code from the checkout on every invocation.
    tools = Path(config["MYBLOG_TOOLS_DIR"])
    tools.mkdir(parents=True, exist_ok=True)
    os.chmod(tools, 0o700)
    for name in ["create_recovery_bundle.py", "verify_recovery_bundle.py", "maintenance.py", "backup_to_drive.py"]:
        content = ("#!/usr/bin/env python3\nimport json, os\nfrom pathlib import Path\n"
                   "root = Path(" + repr(str(root)) + ")\n"
                   "c = json.loads((root / 'instance/runtime.json').read_text())\n"
                   "os.execv(c['MYBLOG_PYTHON'], [c['MYBLOG_PYTHON'], str(root / 'scripts' / " + repr(name) + "), *os.sys.argv[1:]])\n")
        atomic_bytes(tools / name, content.encode(), 0o700)
    backup_service, backup_timer = render_backup_units(root, config)
    atomic_bytes(Path(systemd_dir) / "myblog-backup.service", backup_service.encode(), 0o644)
    atomic_bytes(Path(systemd_dir) / "myblog-backup.timer", backup_timer.encode(), 0o644)
    launcher = Path(launcher or root.parent / "update_myblog.sh")
    content = ("#!/bin/sh\nset -eu\nexport MYBLOG_APP_DIR=" + shlex.quote(str(root)) +
               "\nexport MYBLOG_BOOTSTRAP_PYTHON=" + shlex.quote(config["MYBLOG_PYTHON"]) +
               "\nexec /bin/sh " + shlex.quote(str(root / "scripts/update_myblog.sh")) + ' "$@"\n')
    atomic_bytes(launcher, content.encode(), 0o700)
    if reload:
        subprocess.run(["systemctl", "daemon-reload"], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--database")
    parser.add_argument("--history")
    parser.add_argument("--python", default=None)
    parser.add_argument("--lock")
    parser.add_argument("--proxy", help="Optional non-credentialed proxy for updater Git/pip traffic")
    args = parser.parse_args()
    root = Path(args.app_dir).resolve()
    config = runtime(root)
    config["BLOG_ENV"] = "production"
    if args.proxy:
        from urllib.parse import urlparse
        proxy = urlparse(args.proxy)
        if proxy.scheme not in ("http", "https") or not proxy.hostname or proxy.username or proxy.password:
            raise ValueError("Proxy must be an HTTP(S) URL without embedded credentials")
        config["MYBLOG_PROXY"] = args.proxy
    for key, value in [("BLOG_DB_PATH", args.database), ("BLOG_CONTENT_HISTORY_DIR", args.history), ("MYBLOG_PYTHON", args.python), ("BLOG_MAINTENANCE_LOCK", args.lock)]:
        if value:
            config[key] = str(Path(value).expanduser().absolute()) if key == "MYBLOG_PYTHON" else str(Path(value).resolve())
    if not config.get("BLOG_CONTENT_HISTORY_DIR"):
        raise ValueError("Explicit history directory is required on first install")
    with maintenance_lock(root, config):
        install(root, config)
    print("Runtime settings and launchers installed; service restart is separate.")


if __name__ == "__main__":
    main()
