"""Paint creates: the repaint builds what the model holds.

The founder's box timed paint at ten seconds while the demo
box looked instant, and the difference was never the POST —
it was this: every model-first path (the click's provisional,
the store's record, the booking reply) ended in repaintDay(),
and repaintDay only ever re-seated blocks that already had a
DOM element. Creation lived in syncFromModel, which runs when
a pack fetch lands — so a new block's first paint waited on
the slowest fetch on the machine. On the desk's Windows/NEDB
box that fetch is seconds; the paint inherited them.

Creation now lives in the repaint itself, from the same
renderBlock the reconcile uses: the model is the truth, the
repaint shows the truth, and no fetch of any kind stands
between a click and its block. The poll keeps its reconcile
duties (removals, foreign news) and loses its accidental job
as the paint's gatekeeper.
"""

from pathlib import Path

from django.test import TestCase

ROOT = Path(__file__).parent


def _span(js, start_marker, end_marker):
    start = js.index(start_marker)
    return js[start:js.index(end_marker, start)]


class PaintCreatesBlocksTests(TestCase):
    def setUp(self):
        self.js = (ROOT / "static" / "webui" / "webui.js").read_text()

    def test_repaint_creates_a_missing_block_in_frame(self):
        repaint = _span(
            self.js, "function repaintDay()", "/* ---- in-place reconcile"
        )
        # A model entry with no element is built and seated by
        # the repaint itself — same frame, no fetch.
        self.assertIn("el = renderBlock(e);", repaint)
        self.assertIn("col.appendChild(el);", repaint)
        # The birth is spent inside renderBlock, so a block is
        # born exactly once however often the repaint runs.
        render = _span(self.js, "function renderBlock(entry)", "function effectiveEntries")
        self.assertIn('entry._born = false', render)

    def test_repaint_still_never_touches_a_dragging_block(self):
        repaint = _span(
            self.js, "function repaintDay()", "/* ---- in-place reconcile"
        )
        self.assertIn('el.classList.contains("dragging")', repaint)
        # The dragging guard stands before any creation, so a
        # gesture in hand is never re-seated by a repaint.
        self.assertLess(
            repaint.index('el.classList.contains("dragging")'),
            repaint.index("el = renderBlock(e);"),
        )

    def test_creation_clears_the_columns_open_label(self):
        repaint = _span(
            self.js, "function repaintDay()", "/* ---- in-place reconcile"
        )
        self.assertIn('col.querySelector(".open-label")', repaint)
        self.assertIn("openLabel.remove()", repaint)

    def test_the_reconcile_still_guards_against_double_creation(self):
        sync = _span(self.js, "function syncFromModel()", "function refreshRailData")
        # syncFromModel creates only blocks the document lacks,
        # so a block the repaint already built is never doubled.
        self.assertIn("if (!document.querySelector('.appt-block[data-appt=\"' + e.id + '\"]'))", sync)

    def test_provisional_paint_still_needs_no_fetch(self):
        handler = _span(
            self.js,
            'document.addEventListener("os:provisional"',
            'document.addEventListener("os:unbook"',
        )
        self.assertIn("repaintDay()", handler)
        self.assertNotIn("fetch(", handler)
        self.assertNotIn("pollPack(", handler)
