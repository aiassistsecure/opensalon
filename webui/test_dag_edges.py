"""Explicit DAG edges + the contested-tail rebase.

The journal's plays form a DAG, and these pins hold its two
working parts. Edges: a play on a store-born doc names the
birth it depends on — the edge is written when the play is
queued, persisted with the op (it survives the tab), and
the drain holds any play whose birth is still anywhere in
the queue, while other docs' plays flow past it. Rebase:
when the node rejects a play, its doc is contested — the
still-queued tail holds (never struck) until the node's
fresh word lands through an adopt, which replaces the base
and lifts the hold so the tail replays onto the truth. A
ten-second TTL keeps a doc the node never speaks for again
from holding its tail forever."""

from pathlib import Path

from django.test import TestCase

STATIC = Path(__file__).parent / "static" / "webui"


class DagEdgeTests(TestCase):
    def setUp(self):
        self.src = (STATIC / "shadow.js").read_text()

    def test_plays_carry_their_birth_edge(self):
        for pin in [
            "const birthKeys = {};",
            "birthKeys[ref] = enqueue(op);",
            "wire.after = birthKeys[wire.id];",
            "function enqueuePlay(wire)",
        ]:
            self.assertIn(pin, self.src)
        # Every gesture kind queues as an edge-aware play.
        self.assertEqual(self.src.count("enqueuePlay({"), 4)

    def test_the_drain_honors_edges_per_doc(self):
        for pin in [
            "if (!skip && rec.after && queuedIds.indexOf(rec.after) >= 0)",
            "if (skip) { held += 1; continue; }",
            # a fully-held round still speaks, so the book
            # fetches the node's word the hold is waiting for
            'emit("os:drain", { acked: 0, failed: [{ held: held }] })',
        ]:
            self.assertIn(pin, self.src)

    def test_a_rejection_contests_the_doc_and_the_adopt_rebases(self):
        for pin in [
            "const contestedAt = {};",
            "function contested(id)",
            "Date.now() - at < 10000",
            'if (rec.kind === "create") contestedAt[rec.ref] = Date.now();',
            "else if (rec.id != null) contestedAt[rec.id] = Date.now();",
            "if (!skip && rec.id != null && contested(rec.id)) skip = true;",
        ]:
            self.assertIn(pin, self.src)
        # Both adoption doors lift the hold — the pack seed
        # and the chain adopt each clear the doc they speak
        # for, and the tail replays onto the landed base.
        self.assertEqual(self.src.count("delete contestedAt[entry.id];"), 2)
