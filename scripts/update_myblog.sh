#!/bin/sh
set -eu
APP_DIR="${MYBLOG_APP_DIR:-/home/xyr/myBlog}"
PYTHON="${MYBLOG_BOOTSTRAP_PYTHON:-/home/venv/bin/python}"
case " $* " in
  *" --check "*|*" --help "*)
    exec "$PYTHON" "$APP_DIR/scripts/update_myblog.py" --app-dir "$APP_DIR" "$@"
    ;;
  *)
    exec systemd-run --wait --collect --unit="myblog-update-$$" \
      --property=StandardOutput=journal --property=StandardError=journal \
      "$PYTHON" "$APP_DIR/scripts/update_myblog.py" --app-dir "$APP_DIR" "$@"
    ;;
esac
