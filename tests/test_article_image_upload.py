import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from app import create_app
from app.auth import ADMIN_SESSION_KEY, CSRF_SESSION_KEY


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 16
WEBP_BYTES = b"RIFF" + b"\x10\x00\x00\x00" + b"WEBPVP8 " + b"\x00" * 8


class ArticleImageUploadTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["BLOG_ARTICLE_IMAGE_UPLOAD_DIR"] = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def login(self, client, csrf_token="csrf-token"):
        with client.session_transaction() as session:
            session[ADMIN_SESSION_KEY] = True
            session[CSRF_SESSION_KEY] = csrf_token

    def upload(self, client, payload, filename, csrf_token="csrf-token"):
        return client.post(
            "/edit/article-image",
            headers={"X-CSRF-Token": csrf_token},
            data={"article-image": (BytesIO(payload), filename)},
        )

    def test_upload_requires_admin_login(self):
        with self.app.test_client() as client:
            response = self.upload(client, PNG_BYTES, "article.png")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_upload_requires_csrf_token(self):
        with self.app.test_client() as client:
            self.login(client)
            response = client.post(
                "/edit/article-image",
                data={"article-image": (BytesIO(PNG_BYTES), "article.png")},
            )

        self.assertEqual(response.status_code, 403)

    def test_upload_accepts_supported_images_and_serves_them(self):
        cases = [
            (PNG_BYTES, "article.png"),
            (JPG_BYTES, "article.jpg"),
            (JPG_BYTES, "article.jpeg"),
            (WEBP_BYTES, "article.webp"),
        ]

        with self.app.test_client() as client:
            self.login(client)

            for payload, filename in cases:
                with self.subTest(filename=filename):
                    response = self.upload(client, payload, filename)
                    data = response.get_json()

                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(data["status"], "success")
                    self.assertTrue(data["image_url"].startswith("/media/articles/"))

                    relative_path = data["image_url"].removeprefix(
                        "/media/articles/"
                    ).replace("/", os.sep)
                    uploaded_path = Path(self.temp_dir.name) / relative_path
                    self.assertTrue(uploaded_path.exists())
                    self.assertEqual(uploaded_path.read_bytes(), payload)

                    media_response = client.get(data["image_url"])
                    self.assertEqual(media_response.status_code, 200)
                    self.assertEqual(media_response.get_data(), payload)
                    media_response.close()

    def test_upload_rejects_missing_and_invalid_images(self):
        cases = [
            (b"<svg></svg>", "article.svg"),
            (b"GIF89a" + b"\x00" * 8, "article.gif"),
            (JPG_BYTES, "article.png"),
            (b"", "article.png"),
        ]

        with self.app.test_client() as client:
            self.login(client)
            missing_response = client.post(
                "/edit/article-image",
                headers={"X-CSRF-Token": "csrf-token"},
            )
            self.assertEqual(missing_response.status_code, 400)

            for payload, filename in cases:
                with self.subTest(filename=filename):
                    response = self.upload(client, payload, filename)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.get_json()["status"], "error")

    def test_upload_rejects_oversized_image(self):
        self.app.config["BLOG_ARTICLE_IMAGE_MAX_BYTES"] = 8

        with self.app.test_client() as client:
            self.login(client)
            response = self.upload(client, JPG_BYTES, "article.jpg")

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["status"], "error")


if __name__ == "__main__":
    unittest.main()
