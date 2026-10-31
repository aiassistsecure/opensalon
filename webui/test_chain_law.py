"""The chain law (founder, 2026-10-31): fetch from the internal
store first, then chain calls to the HTTP node on the backend —
and vice versa during writes.

These tests pin the client's half of that law in the shipped
sources, the way this codebase pins its JavaScript contracts:
- the node's pack answer reconciles INTO the store (os:adopt:
  docs land, docs the day no longer holds vanish) instead of
  becoming the render model directly;
- the render model follows the store doc by doc (os:record
  inserts as well as updates, os:vanish removes), on any day;
- the poll never adopts over undrained local plays — the
  pending check stands before the model is touched;
- the client card answers from the store's doc first when the
  node's payload has not arrived, and chains the payload in
  behind it.
"""

from pathlib import Path

from django.test import TestCase

STATIC = Path(__file__).resolve().parent / "static" / "webui"


def read(name):
    return (STATIC / name).read_text(encoding="utf-8")


class ChainLawStoreTests(TestCase):
    def test_adopt_reconciles_the_node_answer_into_the_store(self):
        js = read("shadow.js")
        self.assertIn("function adopt(days)", js)
        self.assertIn('document.addEventListener("os:adopt"', js)
        # Docs land, stale docs are deleted, both are spoken.
        self.assertIn('db.put("appointments"', js)
        self.assertIn('db.delete("appointments"', js)
        self.assertIn('emit("os:vanish"', js)
        self.assertIn('emit("os:record", doc)', js)

    def test_a_doc_lives_on_exactly_one_day_in_the_index(self):
        js = read("shadow.js")
        self.assertIn("function indexDoc(iso, id)", js)
        # Indexing strips the id from every other day's set, so
        # a cross-day move can never be deleted by its old day.
        self.assertIn("if (d !== iso && dayIndex[d]) delete dayIndex[d][id];", js)


class ChainLawModelTests(TestCase):
    def test_build_model_adopts_when_the_store_is_live(self):
        js = read("webui.js")
        self.assertIn('new CustomEvent("os:adopt"', js)
        # The direct assignment survives only as the fallback.
        self.assertIn("days: storeLive ? model.days : pack.days", js)

    def test_record_inserts_and_vanish_removes_by_day(self):
        js = read("webui.js")
        self.assertIn("model.days[doc.day]", js)
        self.assertIn('document.addEventListener("os:vanish"', js)
        self.assertIn("entries.filter(function (e) { return e.id !== d.id; })", js)

    def test_poll_checks_pending_before_touching_the_model(self):
        js = read("webui.js")
        start = js.index("function pollPack()")
        segment = js[start:start + 4000]
        self.assertLess(
            segment.index("storePending"),
            segment.index("buildModel(data, currentDate)"),
            "the pending guard must stand before buildModel, or an "
            "adoption can overwrite undrained plays in the store",
        )

    def test_the_card_answers_from_the_store_first(self):
        js = read("webui.js")
        self.assertIn("function renderRailProvisional(e)", js)
        # The provisional card chains the node's payload behind.
        choose = js[js.index("function choose(block, openSheet)"):]
        choose = choose[:choose.index("\n  }")]
        self.assertIn("renderRailProvisional(entry)", choose)
        self.assertIn("refreshRailData(block.dataset.appt)", choose)
        # And it invents nothing the entry does not know.
        prov = js[js.index("function renderRailProvisional(e)"):]
        prov = prov[:prov.index("function choose(block, openSheet)")]
        self.assertNotIn("client_visits", prov)
        self.assertNotIn("client_email", prov)
        self.assertNotIn("history", prov)
