import os
import re
import unittest

from app import create_app
from app.auth import verify_admin_password


class AdminAuthTest(unittest.TestCase):
    def setUp(self):
        self._saved_env = {
            "BLOG_ADMIN_PASSWORD": os.environ.get("BLOG_ADMIN_PASSWORD"),
            "BLOG_ADMIN_PASSWORD_HASH": os.environ.get("BLOG_ADMIN_PASSWORD_HASH"),
        }
        os.environ.pop("BLOG_ADMIN_PASSWORD", None)
        os.environ.pop("BLOG_ADMIN_PASSWORD_HASH", None)
        self.app = create_app()
        self.app.config["TESTING"] = True

    def tearDown(self):
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_config_password_accepts_wrapped_secret(self):
        self.app.config["BLOG_ADMIN_PASSWORD"] = ' "admin-secret" '

        with self.app.app_context():
            self.assertTrue(verify_admin_password("admin-secret"))

    def test_env_password_overrides_config_password(self):
        self.app.config["BLOG_ADMIN_PASSWORD"] = "config-secret"
        os.environ["BLOG_ADMIN_PASSWORD"] = " env-secret "

        with self.app.app_context():
            self.assertTrue(verify_admin_password("env-secret"))
            self.assertFalse(verify_admin_password("config-secret"))

    def test_invalid_hash_config_does_not_block_plain_password(self):
        self.app.config["BLOG_ADMIN_PASSWORD_HASH"] = "not-a-werkzeug-hash"
        self.app.config["BLOG_ADMIN_PASSWORD"] = "admin-secret"

        with self.app.app_context():
            self.assertTrue(verify_admin_password("admin-secret"))

    def test_admin_login_redirects_after_valid_password(self):
        self.app.config["BLOG_ADMIN_PASSWORD"] = "admin-secret"

        with self.app.test_client() as client:
            response = client.get(self.app.config["ADMIN_LOGIN_PATH"])
            token_match = re.search(
                r'name="csrf_token" value="([^"]+)"',
                response.get_data(as_text=True),
            )
            self.assertIsNotNone(token_match)

            response = client.post(
                self.app.config["ADMIN_LOGIN_PATH"],
                data={
                    "csrf_token": token_match.group(1),
                    "password": "admin-secret",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/manage")


if __name__ == "__main__":
    unittest.main()
