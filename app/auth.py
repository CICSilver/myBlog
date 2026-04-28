import hmac
import os
import secrets
from functools import wraps
from urllib.parse import urlparse

from flask import (
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash


ADMIN_SESSION_KEY = "admin_authenticated"
CSRF_SESSION_KEY = "csrf_token"


def current_admin_authenticated():
    return bool(session.get(ADMIN_SESSION_KEY))


def get_csrf_token():
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def validate_csrf_token():
    expected = session.get(CSRF_SESSION_KEY)
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")

    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(403)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_admin_authenticated():
            return view(*args, **kwargs)

        if _expects_json_response():
            return jsonify({"status": "error", "message": "需要管理员登录。"}), 401

        return redirect(url_for("admin_login", next=request.full_path.rstrip("?")))

    return wrapped


def verify_admin_password(password):
    if not password:
        return False

    password_hash = _get_config_value("BLOG_ADMIN_PASSWORD_HASH")
    if password_hash and check_password_hash(password_hash, password):
        return True

    configured_password = _get_config_value("BLOG_ADMIN_PASSWORD")
    if configured_password:
        return hmac.compare_digest(configured_password, password)

    return False


def admin_login():
    if current_admin_authenticated():
        return redirect(_safe_next_url(request.args.get("next")) or url_for("main.blog_manage"))

    error_message = None

    if request.method == "POST":
        validate_csrf_token()
        password = request.form.get("password", "")

        if verify_admin_password(password):
            session[ADMIN_SESSION_KEY] = True
            session.permanent = True
            return redirect(_safe_next_url(request.form.get("next")) or url_for("main.blog_manage"))

        error_message = "登录失败，请检查管理员密码。"

    return render_template(
        "admin_login.html",
        error_message=error_message,
        next_url=_safe_next_url(request.args.get("next")),
    )


def admin_logout():
    if request.method != "POST":
        abort(405)

    validate_csrf_token()
    session.pop(ADMIN_SESSION_KEY, None)
    session.pop(CSRF_SESSION_KEY, None)
    return jsonify({"status": "success", "message": "已退出登录。"})


def _expects_json_response():
    return (
        request.method not in ("GET", "HEAD")
        or request.accept_mimetypes.best == "application/json"
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )


def _safe_next_url(next_url):
    if not next_url:
        return None

    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc or not next_url.startswith("/"):
        return None

    return next_url


def _get_config_value(key):
    env_value = os.environ.get(key)
    if _has_text(env_value):
        return _normalize_secret_value(env_value)

    return _normalize_secret_value(current_app.config.get(key))


def _has_text(value):
    return isinstance(value, str) and value.strip() != ""


def _normalize_secret_value(value):
    if not isinstance(value, str):
        return value

    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()

    return value
