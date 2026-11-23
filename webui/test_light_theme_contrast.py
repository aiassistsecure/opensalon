"""Light-theme contrast: dark text on the light workspace.

The founder's report of 2026-11-23: Insights finally loaded on
the pilot box — and rendered white on white. The dark theme's
base text colour (--tx, near-white) was inherited by the light
pages; components that set a light background without also
setting a text colour (the POS/Insights cards, the product
shelf, the report tables) drew near-white text on near-white
cards. The law that replaced it: the light workspace's .main
carries a dark base text colour, scoped so the dark sidebar,
tab bar and modals keep the dark theme's text, and the light
card components set their colour explicitly.
"""
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase


def _rule(css, selector):
    start = css.index(selector)
    return css[start:css.index("}", start)]


class LightThemeContrastTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        path = finders.find("webui/webui.css")
        with open(path, encoding="utf-8") as handle:
            cls.css = handle.read()

    def test_light_main_carries_dark_base_text(self):
        rule = _rule(self.css, "body.page-light .main { color:")
        self.assertIn("color: #1d2530", rule)

    def test_light_fix_is_scoped_to_main(self):
        # An unscoped body.page-light colour would flip the dark
        # sidebar and tab bar to dark text on dark glass.
        self.assertNotIn("body.page-light { color", self.css)
        self.assertNotIn("body.page-light{color", self.css)

    def test_insights_cards_set_dark_text(self):
        # Insights is built from .pos-card sections and
        # .rep-table tables — the founder's white-on-white page.
        self.assertIn("color:#1d2530", _rule(self.css, ".pos-card{"))
        thead = _rule(self.css, ".page-light .main thead th")
        self.assertIn("background: #fbf7ec", thead)
        self.assertIn("color: #8a826f", thead)

    def test_shelf_sets_dark_text(self):
        self.assertIn("color:#1d2530", _rule(self.css, ".shelf{"))
        self.assertIn(
            "color:#1d2530", _rule(self.css, ".shelf-search input{")
        )
