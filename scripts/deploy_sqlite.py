"""Historical one-off cutover entry point, retained only to fail safely."""
import sys


if __name__ == "__main__":
    sys.exit(
        "This one-off cutover tool is retired. Back up and stop the service, "
        "run migrate_sqlite.py with explicit source/target, then install_runtime.py. "
        "For an existing SQLite deployment use update_myblog.sh; "
        "for recovery use maintenance.py restore --confirm-stop. "
        "No files or services were changed."
    )
