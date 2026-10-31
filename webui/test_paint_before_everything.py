"""Paint before EVERYTHING: the click's paint pays for nothing.

The founder's timing on his own box improved (10s -> 6-8s)
but the ask never changed: "just need that on click paint."
The store path still sequenced the paint behind the embedded
engine's synchronous birth work — the record handler repainted
inside createLocal, after its puts and journaling. On a fast
machine that is invisible; on the desk's machine it is the
whole complaint.

So the modal now paints FIRST, in the pure model, from the
desk's own facts, under a ref it mints — and only then asks
the store to birth the doc under that very ref. The store's
record finds the block already standing and adopts it in
place; the rename later swaps in the node's true entry. One
block throughout, and the first paint depends on nothing but
the model and the repaint.

Two guards ride along: if the store takes the click but not
the birth, the pre-paint comes off QUIETLY (no false alarm on
the notice line) and the POST path paints its own; and the
preserved journal restores through a working window — newest
5,000 entries inside 30 days — because the node holds the
durable archive and an unbounded in-tab journal would tax
every boot and write a little more each week.
"""

from pathlib import Path

from django.test import TestCase

ROOT = Path(__file__).parent


class PaintBeforeEverythingTests(TestCase):
    def setUp(self):
        self.js = (ROOT / "static" / "webui" / "webui.js").read_text()
        self.shadow = (ROOT / "static" / "webui" / "shadow.js").read_text()

    def test_the_modal_paints_before_it_asks_the_store(self):
        # The store branch of the save handler: the provisional
        # dispatch precedes the create dispatch, and the create
        # carries the paint's ref.
        start = self.js.index("var paintRef")
        branch = self.js[start:self.js.index('fetch("/daybook/book/"', start)]
        self.assertIn('"tmp_" + Date.now()', branch)
        self.assertIn('new CustomEvent("os:provisional"', branch)
        self.assertIn('new CustomEvent("os:create"', branch)
        self.assertLess(
            branch.index('new CustomEvent("os:provisional"'),
            branch.index('new CustomEvent("os:create"'),
        )
        self.assertIn("ref: paintRef", branch)
        # ...and only after a handled birth does the modal close.
        self.assertIn(
            "if (createEv.detail.handled) { hide(); return; }", branch
        )

    def test_a_refused_birth_unpaints_quietly(self):
        start = self.js.index("var paintRef")
        branch = self.js[start:self.js.index('fetch("/daybook/book/"', start)]
        self.assertIn('new CustomEvent("os:unbook"', branch)
        self.assertIn("quiet: true", branch)
        # The unbook handler honors the quiet flag: a handoff
        # between paint paths is not a failure to announce.
        handler = self.js[
            self.js.index('addEventListener("os:unbook"'):
            self.js.index("var dbNoticeTimer")
        ]
        self.assertIn("if (!d.quiet)", handler)

    def test_the_store_births_under_the_paints_ref(self):
        body = self.shadow[
            self.shadow.index("function createLocal"):
            self.shadow.index("function undo")
        ]
        self.assertIn("detail.ref", body)
        self.assertIn('indexOf("tmp_") === 0', body)
        # The doc still wears the ref it was born under.
        self.assertIn("id: ref, day: p.date", body)

    def test_the_record_adopts_a_standing_block_in_place(self):
        handler = self.js[
            self.js.index('addEventListener("os:record"'):
            self.js.index('addEventListener("os:vanish"')
        ]
        # A known id takes the store's fields — no second push.
        self.assertIn("if (e.id === doc.id)", handler)
        self.assertIn("found = true", handler)

    def test_the_journal_restores_through_a_window(self):
        body = self.shadow[
            self.shadow.index("async function restorePreserved"):
            self.shadow.index("async function recoverQueue")
        ]
        self.assertIn("30 * 86400000", body)
        self.assertIn("i >= 5000", body)
        self.assertIn('idbDeleteIn("journal", rec.key)', body)
        self.assertIn('idbDeleteIn("journal", item.rec.key)', body)
        # The attested chain head is never windowed out.
        self.assertIn('rec.key === "chain:last"', body)
