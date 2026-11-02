"""Held plays: a wait is not a failure, and a dead birth frees its tail.

The desk's report, 2026-11-02: click check-in and the page
becomes unresponsive; checkout the same; click Notes and
nothing happens; only F5 unlocks it, and the server logs
stay clean. The fault was in the page's own store code, in
three linked pieces:

A play chained onto a store-born booking (a check-in tapped
on a booking seconds old) waits for the node to name the
birth. If that naming never lands — the node refused the
birth, answered without an id, or named it in a tab that has
since closed — the play held FOREVER: the only door out of
the queue was a drain batch, and a held play is never in
one. The name map that could have freed it was tab memory,
lost on every reload, while the play itself was preserved
in the app's durable mirror and restored at every boot.

And while anything held, the drain spoke for it on every
900ms round — a drain event carrying a failure — and the
day book answers every failed drain with a full rebuild of
itself. Twice a second, endlessly: clicks landed on
elements mid-rebuild, the rail was recreated under the
desk's finger, and the page read as frozen. F5 restarted
the page; the preserved queue restarted the loop.

The law now: a birth that settles without a name strikes
its chained plays in the same breath; the names the node
gives are preserved with the journal, so a play recovered
in a fresh tab still resolves; recovery strikes any play
that can never resolve rather than restoring it into a
hold that cannot lift; a hold speaks once per episode,
not once per round; and the book rebuilds only on the
node's actual refusals, never over a wait.
"""

from pathlib import Path

from django.test import TestCase

ROOT = Path(__file__).parent


class HeldPlayTests(TestCase):
    def setUp(self):
        self.js = (ROOT / "static" / "webui" / "webui.js").read_text()
        self.shadow = (ROOT / "static" / "webui" / "shadow.js").read_text()

    def drain_body(self):
        return self.shadow[
            self.shadow.index("async function drain"):
            self.shadow.index('window.addEventListener("pagehide"')
        ]

    def test_a_refused_birth_strikes_its_chained_plays(self):
        body = self.drain_body()
        # The vanish branch of a settled-without-a-name create
        # strikes the birth's tail in the same breath.
        self.assertIn("strikePlays(rec.ref, key)", body)
        strike = self.shadow[
            self.shadow.index("function strikePlays"):
            self.shadow.index("let lastChain")
        ]
        # A play is the birth's own when it rides under the
        # ref or names the birth as its edge; births
        # themselves are never struck by another birth's fall.
        self.assertIn("rec.id !== ref && rec.after !== birthKey", strike)
        self.assertIn('rec.kind === "create"', strike)
        # Struck means out of the store, the mirror, and the
        # queue — all three, or the hold survives somewhere.
        self.assertIn('db.delete("outbox", k)', strike)
        self.assertIn("idbDelete(k)", strike)
        self.assertIn("queuedIds.splice(at, 1)", strike)

    def test_the_name_map_is_preserved_with_the_journal(self):
        # The drain preserves the name the node gives a birth.
        self.assertIn(
            'idbPutIn("journal", "rename:" + rec.ref, { to: r.id })',
            self.drain_body(),
        )
        # Boot reads the names home before the queue recovers.
        restore = self.shadow[
            self.shadow.index("async function restorePreserved"):
            self.shadow.index("async function recoverQueue")
        ]
        self.assertIn('rec.key.indexOf("rename:") === 0', restore)
        self.assertIn("renames[rec.key.slice(7)] = rec.to", restore)

    def test_recovery_strikes_plays_that_can_never_resolve(self):
        recover = self.shadow[
            self.shadow.index("async function recoverQueue"):
            self.shadow.index("function seed")
        ]
        # The two honest resolutions are named in the open:
        # the birth still queued here, or the preserved name.
        self.assertIn("birthRefs[rec.id]", recover)
        self.assertIn(
            "renames[rec.id] == null && !birthRefs[rec.id]", recover
        )
        self.assertIn("idbDelete(rec.key)", recover)

    def test_a_hold_speaks_once_per_episode(self):
        body = self.drain_body()
        # The held set is gathered so the episode has a shape…
        self.assertIn("heldKeys.push(key)", body)
        # …and spoken only when that shape is news.
        self.assertIn("if (sig !== lastHeldSig)", body)
        self.assertIn("lastHeldSig = sig", body)
        # The node's word resets the episode: a later hold is
        # a new episode and may speak again.
        self.assertIn('lastHeldSig = ""', body)
        # The retry cadence itself survives — a contested hold
        # still lifts on its TTL and drains then.
        self.assertIn("scheduleDrain(900)", body)

    def test_the_book_does_not_rebuild_over_a_hold(self):
        handler = self.js[
            self.js.index('addEventListener("os:drain"'):
            self.js.index('addEventListener("os:undo-move"')
        ]
        # Held notices are filtered out of the failure set…
        self.assertIn("f.held == null", handler)
        # …and only what remains earns the rebuild.
        self.assertIn("if (refused.length)", handler)
        self.assertIn("refreshDay(", handler)
        self.assertIn("scheduleStoreRefresh()", handler)
