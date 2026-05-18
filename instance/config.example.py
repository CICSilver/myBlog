import os


def _env(name, default=None):
    value = os.environ.get(name)
    if isinstance(value, str):
        value = value.strip()
    return value or default


# Copy this file to instance/config.py on the server, then set real secrets
# either as environment variables or literal values below.
BLOG_ADMIN_PASSWORD = _env("BLOG_ADMIN_PASSWORD")
BLOG_ADMIN_PASSWORD_HASH = _env("BLOG_ADMIN_PASSWORD_HASH")
BLOG_ADMIN_LOGIN_PATH = _env("BLOG_ADMIN_LOGIN_PATH", "/__silver-admin-login")
BLOG_SECRET_KEY = _env("BLOG_SECRET_KEY")
BLOG_TRUST_PROXY_HEADERS = _env("BLOG_TRUST_PROXY_HEADERS", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Example literal local-only values:
# BLOG_ADMIN_PASSWORD = "change-this-admin-password"
# BLOG_SECRET_KEY = "change-this-random-secret-key"
