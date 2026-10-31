"""Paint before print: the fallback paints too, and the
store's state is visible.

The founder's law, extended to every tab: a confirmed
booking paints from the desk's own facts in the click's
frame, BEFORE finalization — the embedded store is the
fast path, never a gate. On a tab whose store is not live,
the modal paints a provisional block (dashed gold edge: not
the node's word yet), closes on it, and lets the POST
finalize behind; the node's entry swaps the provisional
out, a refusal takes it off and says so on the book's
notice line. And the dual store is no longer a matter of
faith: the sidebar chip says which world the tab is in."""

from pathlib import Path

from django.test import TestCase

ROOT = Path(__file__).parent


class ProvisionalPaintTests(TestCase):
    def setUp(self):
        self.js = (ROOT / "static" / "webui" / "webui.js").read_text()
        self.css = (ROOT / "static" / "webui" / "webui.css").read_text()
        self.base = (ROOT / "templates" / "webui" / "base.html").read_text()
        self.main = (
            ROOT / "templates" / "webui" / "_daybook_main.html"
        ).read_text()

    def test_the_modal_paints_provisional_before_it_posts(self):
        for pin in [
            "var docFacts = {",
            'new CustomEvent("os:provisional"',
            '"prov_" + Date.now()',
            "provisional: true",
            # the booked answer and the refusal both carry
            # the provisional's ref back to the book
            "provisional: provRef",
            'new CustomEvent("os:unbook"',
        ]:
            self.assertIn(pin, self.js)
        # paint first: the provisional dispatch precedes the
        # finalizing fetch in the save handler
        self.assertLess(
            self.js.index('new CustomEvent("os:provisional"'),
            self.js.index('fetch("/daybook/book/"'),
        )

    def test_the_book_swaps_and_unbooks(self):
        for pin in [
            'addEventListener("os:provisional"',
            'addEventListener("os:unbook"',
            "if (d.provisional) {",
            "return e.id === d.provisional;",
            "function showDbNotice(message)",
            '(entry.provisional ? " b-prov" : "")',
        ]:
            self.assertIn(pin, self.js)
        self.assertIn('id="dbNotice"', self.main)
        self.assertIn(".appt-block.b-prov", self.css)
        self.assertIn(".db-notice", self.css)

    def test_the_store_chip_says_which_world(self):
        self.assertIn('id="storeChip"', self.base)
        for pin in [
            'document.body.dataset.shadow === "live"',
            'document.body.dataset.rosterStore === "live"',
            '"Local store live"',
            '"Server mode"',
        ]:
            self.assertIn(pin, self.js)
        self.assertIn(".store-chip.is-live .store-dot", self.css)
