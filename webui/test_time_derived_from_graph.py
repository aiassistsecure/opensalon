"""Time is derived from the graph — never recorded text.

The founder dragged a 9:30 block to an 8 AM seat and the
card still read 9:30: the pack entry carries a time_label
string stamped once, when the booking was recorded, and
paintBlock preferred that string over the entry's own
minutes. The graph had moved; the text had not, because the
text was a record, not a derivation.

So the label is now a pure function of the same start/end
minutes that place the block — text and seat are the same
fact on every paint — and the flying tile relabels itself
from the snapped graph position on every drag move, so the
card in the hand reads the hour it is hovering in real
time. (fmtClock and the server's _fmt_time are the same
algorithm, so derived text matches served text word for
word; the server's label may still ride the pack for other
consumers, but the grid never reads it again.)
"""

from pathlib import Path

from django.test import TestCase

ROOT = Path(__file__).parent


def _span(js, start_marker, end_marker):
    start = js.index(start_marker)
    return js[start:js.index(end_marker, start)]


class TimeDerivedFromGraphTests(TestCase):
    def setUp(self):
        self.js = (ROOT / "static" / "webui" / "webui.js").read_text()

    def test_paint_derives_the_label_from_the_minutes(self):
        paint = _span(self.js, "function paintBlock(el, entry, info)", "function renderBlock")
        self.assertIn(
            'fmtClock(entry.start_min) + " – " + fmtClock(entry.end_min)',
            paint,
        )

    def test_paint_never_reads_the_recorded_label(self):
        paint = _span(self.js, "function paintBlock(el, entry, info)", "function renderBlock")
        self.assertNotIn("entry.time_label", paint)

    def test_the_flying_tile_relabels_from_the_graph_on_move(self):
        drag = _span(self.js, "function bindDrag(onlyTile)", "var pendingReselect")
        # The tile's own time text is set inside the move
        # handler, from the snapped start the ghost also uses.
        self.assertIn('tile.querySelector(".b-time")', drag)
        move = _span(drag, "function onMove(e)", "function finish(commit)")
        self.assertIn("tileTime.textContent", move)
        self.assertIn("fmt(dayStartMin + snapped)", move)
        # ...and the assignment rides the same snapped value
        # the ghost announces, not the tile's recorded start.
        self.assertLess(
            move.index('ghost.querySelector(".ghost-time")'),
            move.index("tileTime.textContent"),
        )
