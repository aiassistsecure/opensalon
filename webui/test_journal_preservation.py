"""Journal preservation: the chain is kept in the app.

The founder's two-database design: the queue journal lives
in the app's client-side NEDB, PRESERVED — not session
memory with an HTTP rehydrate at boot. These pins hold the
shape: the whole chain (docs + journal, beside the outbox)
is mirrored into the app's durable memory on every write,
through single wrappers so the copies cannot drift; boot
restores the preserved chain before the store declares
itself, prunes outside the working window, and speaks for
births that outlived their tab."""

from pathlib import Path

from django.test import TestCase

STATIC = Path(__file__).parent / "static" / "webui"


class JournalPreservationTests(TestCase):
    def setUp(self):
        self.src = (STATIC / "shadow.js").read_text()

    def test_the_whole_chain_is_preserved_not_just_the_queue(self):
        for pin in [
            'indexedDB.open("opensalon-shadow", 2)',
            '["outbox", "docs", "journal"]',
            'idbPutIn("docs", String(id), { doc: json })',
            'idbPutIn("journal", key, { op: json })',
        ]:
            self.assertIn(pin, self.src)

    def test_every_write_runs_through_the_wrappers(self):
        # Raw engine writes to the two collections exist only
        # inside the wrappers and the boot restore itself —
        # no write site can bypass the preserved copy.
        self.assertEqual(self.src.count('db.put("appointments"'), 2)
        self.assertEqual(self.src.count('db.put("ops"'), 2)
        for pin in [
            "function putDoc(id, doc)",
            "function delDoc(id)",
            "function journal(op)",
            "putDoc(entry.id, doc);",
            "putDoc(ref, doc);",
            "putDoc(r.id, entry);",
        ]:
            self.assertIn(pin, self.src)
        self.assertEqual(self.src.count("journal(op);"), 2)

    def test_boot_restores_before_it_declares(self):
        restore_at = self.src.index("await restorePreserved()")
        ready_at = self.src.index('emit("os:shadow-ready"')
        self.assertLess(restore_at, ready_at)
        for pin in [
            "function restorePreserved()",
            "isoDays(-14)",
            "isoDays(14)",
            # births that outlived their tab are spoken for
            "restored.births.forEach",
            'emit("os:restored"',
        ]:
            self.assertIn(pin, self.src)
