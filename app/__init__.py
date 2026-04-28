from flask import Flask
from tinydb import TinyDB
from datetime import timedelta
import os

# 数据库文件路径
db_path = './db/blog_db.json'

# 确保父目录存在
os.makedirs(os.path.dirname(db_path), exist_ok=True)

# 初始化 TinyDB
blog_db = TinyDB(db_path)  # 基础数据库

def create_app():
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    app.config["SECRET_KEY"] = _get_secret_key()
    app.config["ADMIN_LOGIN_PATH"] = _get_admin_login_path()
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

    return app


def _is_development():
    return os.environ.get("BLOG_ENV", "development").lower() != "production"


def _get_secret_key():
    secret_key = os.environ.get("BLOG_SECRET_KEY")
    if secret_key:
        return secret_key

    if _is_development():
        return "dev-only-change-this-secret-key"

    raise RuntimeError("BLOG_SECRET_KEY must be configured in production.")


def _get_admin_login_path():
    path = os.environ.get("BLOG_ADMIN_LOGIN_PATH", "/__silver-admin-login")
    if not path.startswith("/"):
        path = "/" + path
    return path
