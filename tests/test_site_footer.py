import unittest
from html.parser import HTMLParser
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


class FooterParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_footer = False
        self.links = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "footer":
            self.in_footer = True
        if tag == "a" and self.in_footer:
            self.links.append(attributes)

    def handle_endtag(self, tag):
        if tag == "footer":
            self.in_footer = False

    def handle_data(self, data):
        if self.in_footer:
            self.text.append(data)


class SiteFooterTest(unittest.TestCase):
    def test_shared_layout_renders_icp_link(self):
        root = Path(__file__).resolve().parents[1]
        environment = Environment(
            loader=FileSystemLoader(root / "templates"),
            autoescape=select_autoescape(),
        )
        template = environment.from_string(
            '{% extends "base.html" %}{% block site_header %}{% endblock %}'
        )
        html = template.render(
            url_for=lambda endpoint, filename, **kwargs: "/static/" + filename,
            csrf_token=lambda: "test-token",
        )
        parser = FooterParser()
        parser.feed(html)
        self.assertEqual(len(parser.links), 1)
        self.assertEqual(parser.links[0]["href"], "https://beian.miit.gov.cn/")
        self.assertEqual(parser.links[0]["target"], "_blank")
        self.assertIn("noopener", parser.links[0]["rel"].split())
        self.assertEqual(
            "".join(parser.text).strip(),
            "\u82cfICP\u59072026065932\u53f7-1",
        )
        self.assertIn("/static/css/site-footer.css", html)
