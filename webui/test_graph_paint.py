"""Graph status faces + instant checkout paint + receipt prefill.

The founder's status language for the graph (2026-11-02): a
checked-in guest's block wears a DIFFERENT COLOR and a
HIGHLIGHT (she is in the building — the whole room reads it
at a glance), and a checked-out, paid guest's block goes
GREEN. Both render paths carry it — the server's block
template and the client's renderBlock/paintBlock — through
one class pair, `st-<status>`.

Checkout paints instantly: tapping Complete flips the
visit's blocks to completed in the local model before the
server answers (the founder timed a ten-second poll wait
for "visit had been settled"), and a refusal restores the
graph exactly. The receipt's address is seeded from the
client's card the moment the modal opens — prefilled where
the card has one, an empty waiting input where it doesn't.
"""

from pathlib import Path

from django.test import TestCase


class GraphPaintSourceTests(TestCase):
    def setUp(self):
        root = Path(__file__).parent
        self.main_html = (
            root / "templates" / "webui" / "_daybook_main.html"
        ).read_text()
        self.block_html = (
            root / "templates" / "webui" / "_block.html"
        ).read_text()
        self.js = (root / "static" / "webui" / "webui.js").read_text()
        self.css = (root / "static" / "webui" / "webui.css").read_text()

    def _rule(self, selector):
        start = self.css.index(selector)
        return self.css[start:self.css.index("}", start)]

    def _handler(self):
        start = self.js.index('coEl("coComplete").addEventListener')
        end = self.js.index('coEl("coSendReceipt")', start)
        return self.js[start:end]

    def _co_render(self):
        start = self.js.index("function coRender()")
        end = self.js.index("function armCheckout()", start)
        return self.js[start:end]

    # ---- the status class on both render paths ----

    def test_server_block_carries_the_status_class(self):
        # _daybook_main.html renders its blocks through
        # _block.html; the include is the path, the class is
        # on the block itself.
        self.assertIn('_block.html', self.main_html)
        self.assertIn("st-{{ block.status }}", self.block_html)

    def test_render_block_adds_the_status_class(self):
        self.assertIn('" st-" + entry.status', self.js)

    def test_paint_block_swaps_the_status_class(self):
        self.assertIn('el.classList.add("st-" + entry.status)', self.js)
        self.assertIn('el.classList.remove("st-" + el.dataset.status)', self.js)

    # ---- the faces themselves ----

    def test_arrived_face_has_color_and_highlight(self):
        rule = self._rule(".appt-block.st-arrived")
        # A shifted face (its own background) AND a highlight
        # (the ring/glow lives in box-shadow).
        self.assertIn("background", rule)
        self.assertIn("box-shadow", rule)
        self.assertIn("0 0 0 2px", rule)

    def test_completed_face_is_green(self):
        rule = self._rule(".appt-block.st-completed")
        self.assertIn("#2f8f4e", rule)
        light = self._rule(".page-light .appt-block.st-completed")
        self.assertIn("#43a35f", light)

    # ---- instant checkout paint ----

    def test_settled_paint_helper_exists(self):
        self.assertIn("function paintSettledLocally()", self.js)

    def test_paint_fires_after_the_guard_before_the_fetch(self):
        handler = self._handler()
        guard = handler.index("still saving")
        paint = handler.index("paintSettledLocally()")
        fetch = handler.index("fetch(layout.dataset.checkout")
        self.assertLess(guard, paint)
        self.assertLess(paint, fetch)

    def test_refusal_and_failure_restore_the_paint(self):
        handler = self._handler()
        # Once for a refused sale (!data.ok), once for a
        # fetch that never answered (.catch).
        self.assertGreaterEqual(handler.count("restoreSettledPaint();"), 2)

    # ---- receipt prefill from the client's card ----

    def test_co_render_seeds_the_receipt_email(self):
        render = self._co_render()
        self.assertIn('coEl("coEmail").value = d.client_email || "";', render)
        self.assertIn('emailRow.classList.remove("hidden")', render)
