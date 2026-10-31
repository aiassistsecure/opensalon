"""Service fine print: every block names its service,
no click needed.

The founder's law from his own screen (2026-10-31): "I need
to see everyones service in fine print under their name
without clicking." The density classes used to spend the
service first — mini hid the whole service band, micro hid
everything but the name. Now the degradation spends the
time row and the price before it ever spends the service:
mini keeps name + a one-line fine-print service under it
(band tightened to fit), and micro — one physical line —
rides the service on the name line in the same fine print.
The rule holds in all three block builders: the server
template, the client factory, and the painter that fills
them."""

from pathlib import Path

from django.test import TestCase

ROOT = Path(__file__).parent


class ServiceFinePrintTests(TestCase):
    def setUp(self):
        self.js = (ROOT / "static" / "webui" / "webui.js").read_text()
        self.css = (ROOT / "static" / "webui" / "webui.css").read_text()
        self.block = (
            ROOT / "templates" / "webui" / "_block.html"
        ).read_text()

    def test_mini_no_longer_hides_the_service_band(self):
        self.assertNotIn(
            ".appt-block.mini .b-top, .appt-block.mini .b-services",
            self.css,
        )
        self.assertIn(".appt-block.mini .b-top { display: none; }", self.css)
        self.assertIn(
            ".appt-block.mini .b-service { -webkit-line-clamp: 1;",
            self.css,
        )

    def test_micro_rides_the_service_on_the_name_line(self):
        self.assertIn(".b-svc-inline", self.css)
        self.assertIn(
            ".appt-block.micro .b-svc-inline { display: inline; }",
            self.css,
        )
        # both builders carry the span, and the painter fills it
        self.assertIn('<span class="b-svc-inline"></span>', self.js)
        self.assertIn("svcInline.textContent = entry.service;", self.js)
        self.assertIn(
            '<span class="b-svc-inline">{{ block.service_name }}</span>',
            self.block,
        )
