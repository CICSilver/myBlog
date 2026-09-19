import unittest
from html.parser import HTMLParser
from pathlib import Path

from flask import Flask, render_template_string


class IconParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.icons = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "link" and attributes.get("rel") == "icon":
            self.icons.append(attributes)


class SiteIconTest(unittest.TestCase):
    def test_shared_layout_serves_selected_png_icon(self):
        root = Path(__file__).resolve().parents[1]
        app = Flask(
            __name__,
            template_folder=str(root / "templates"),
            static_folder=str(root / "static"),
        )
        app.add_url_rule("/api/weather", endpoint="main.api_weather", view_func=lambda: "")
        with app.test_request_context():
            html = render_template_string(
                '{% extends "base.html" %}{% block site_header %}{% endblock %}',
                csrf_token=lambda: "test-token",
            )
        parser = IconParser()
        parser.feed(html)
        self.assertEqual(len(parser.icons), 1)
        icon = parser.icons[0]
        self.assertEqual(icon["type"], "image/png")
        self.assertEqual(icon["href"], "/static/images/favicon-path-circle.png")
        with app.test_client() as client:
            response = client.get(icon["href"])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "image/png")
            self.assertTrue(response.data.startswith(b"\x89PNG\r\n\x1a\n"))
            response.close()


if __name__ == "__main__":
    unittest.main()
