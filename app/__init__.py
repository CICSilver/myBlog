from flask import Flask
from tinydb import TinyDB
from datetime import timedelta
import os

from app.content_history import (
    default_history_dir,
    list_history,
    restore_snapshot,
    snapshot_content_db,
)

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据库文件路径
db_path = os.environ.get("BLOG_DB_PATH") or os.path.join(project_root, "db", "blog_db.json")

# 确保父目录存在
os.makedirs(os.path.dirname(db_path), exist_ok=True)

# 初始化 TinyDB
blog_db = TinyDB(db_path)  # 基础数据库

def create_app():
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    app.config.from_pyfile(_local_config_path(), silent=True)
    app.config["SECRET_KEY"] = _get_secret_key(app)
    app.config["ADMIN_LOGIN_PATH"] = _get_admin_login_path(app)
    app.config["BLOG_CONTENT_HISTORY_DIR"] = _get_content_history_dir(app)
    app.config["BLOG_DB_PATH"] = db_path
    app.permanent_session_lifetime = timedelta(days=14)

    from app.routes import main
    from app.auth import (
        admin_login,
        current_admin_authenticated,
        get_csrf_token,
    )

    app.register_blueprint(main)
    app.add_url_rule(
        app.config["ADMIN_LOGIN_PATH"],
        endpoint="admin_login",
        view_func=admin_login,
        methods=["GET", "POST"],
    )

    @app.context_processor
    def inject_auth_context():
        return {
            "current_admin_authenticated": current_admin_authenticated,
            "csrf_token": get_csrf_token,
        }

    _register_history_commands(app)

    return app


def _local_config_path():
    return os.path.join(project_root, "instance", "config.py")


def _get_config_value(app, key, default=None):
    return os.environ.get(key) or app.config.get(key, default)


def _is_development(app):
    return str(_get_config_value(app, "BLOG_ENV", "development")).lower() != "production"


def _get_secret_key(app):
    secret_key = _get_config_value(app, "BLOG_SECRET_KEY")
    if secret_key:
        return secret_key

    if _is_development(app):
        return "dev-only-change-this-secret-key"

    raise RuntimeError("BLOG_SECRET_KEY must be configured in production.")


def _get_admin_login_path(app):
    path = _get_config_value(app, "BLOG_ADMIN_LOGIN_PATH", "/__silver-admin-login")
    if not path.startswith("/"):
        path = "/" + path
    return path


def _get_content_history_dir(app):
    return _get_config_value(app, "BLOG_CONTENT_HISTORY_DIR") or default_history_dir()


def _register_history_commands(app):
    import click

    @app.cli.command("history-snapshot")
    @click.option("--reason", default="manual", help="Snapshot reason recorded in manifest.")
    def history_snapshot(reason):
        entry = snapshot_content_db(
            app.config["BLOG_DB_PATH"],
            reason,
            history_dir=app.config["BLOG_CONTENT_HISTORY_DIR"],
        )
        if entry is None:
            click.echo("No database file exists yet.")
            return
        click.echo(entry["path"])

    @app.cli.command("history-list")
    @click.option("--limit", default=20, show_default=True, help="Maximum entries to show.")
    def history_list(limit):
        entries = list_history(app.config["BLOG_CONTENT_HISTORY_DIR"], limit=limit)
        if not entries:
            click.echo("No history snapshots found.")
            return
        for entry in entries:
            click.echo(
                "{0}  {1}  {2}".format(
                    entry.get("timestamp", ""),
                    entry.get("reason", ""),
                    entry.get("path", ""),
                )
            )

    @app.cli.command("history-restore")
    @click.argument("snapshot_path")
    def history_restore(snapshot_path):
        snapshot_content_db(
            app.config["BLOG_DB_PATH"],
            "pre-restore",
            history_dir=app.config["BLOG_CONTENT_HISTORY_DIR"],
        )
        restore_snapshot(snapshot_path, app.config["BLOG_DB_PATH"])
        snapshot_content_db(
            app.config["BLOG_DB_PATH"],
            "post-restore",
            history_dir=app.config["BLOG_CONTENT_HISTORY_DIR"],
        )
        click.echo("Restored {0}".format(snapshot_path))
