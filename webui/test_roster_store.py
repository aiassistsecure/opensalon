"""Roster store promotion, stage 2: the roster book's
gestures become store plays.

The page hydrates the embedded store from a seed cut from
the very patterns and overrides it renders; roster-store.js
records plays there first, repaints the column from the
store's resolved word, and drains to /roster/apply/ — whose
weekly answers now name the pattern id, so a play chained
onto a just-placed pattern can carry the real id. When the
store never wakes, the book's form posts run exactly as
before."""

import datetime
import json
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from saloncore.models import Salon
from team.models import RosterPattern, ShiftOverride, StaffMember

STATIC = Path(__file__).parent / "static" / "webui"
MONDAY = datetime.date(2026, 11, 2)


class RosterSeedTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint On The Avenue")
        self.member = StaffMember.objects.create(
            display_name="Maribel Gonzalez", salon=self.salon
        )
        self.pat = RosterPattern.objects.create(
            staff_member=self.member, weekday=MONDAY.weekday(),
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0),
        )

    def seed(self, **kw):
        resp = self.client.get(reverse("webui:roster"), kw)
        self.assertEqual(resp.status_code, 200)
        return resp, resp.context["roster_seed"]

    def test_the_seed_mirrors_the_rendered_book(self):
        resp, seed = self.seed(date="2026-11-02")
        self.assertEqual(seed["date"], "2026-11-02")
        self.assertEqual(seed["weekday"], MONDAY.weekday())
        self.assertEqual(seed["apply_url"], reverse("webui:roster_apply"))
        self.assertEqual(len(seed["patterns"]), 1)
        entry = seed["patterns"][0]
        self.assertEqual(entry["id"], self.pat.pk)
        self.assertEqual(entry["member"], self.member.pk)
        self.assertEqual((entry["start_min"], entry["end_min"]), (540, 1020))
        self.assertEqual(seed["overrides"], {})
        # …and the page carries both the seed and the store.
        body = resp.content.decode()
        self.assertIn('id="roster-seed"', body)
        self.assertIn("roster-store.js", body)

    def test_the_seed_carries_the_dates_override(self):
        ShiftOverride.objects.create(
            staff_member=self.member, date=MONDAY, is_off=True,
        )
        _resp, seed = self.seed(date="2026-11-02")
        ov = seed["overrides"][str(self.member.pk)]
        self.assertTrue(ov["is_off"])


class RosterApplyIdTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint On The Avenue")
        self.member = StaffMember.objects.create(
            display_name="Dawn Davalos", salon=self.salon
        )
        self.url = reverse("webui:roster_apply")

    def apply(self, ops):
        resp = self.client.post(
            self.url,
            data=json.dumps({"ops": ops}),
            content_type="application/json",
        )
        return resp.json()["results"]

    def test_a_weekly_place_answers_with_its_pattern_id(self):
        (result,) = self.apply([{
            "kind": "place", "member": self.member.pk,
            "date": "2026-11-02", "weekly": True,
            "start": "09:00", "end": "17:00",
        }])
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["pattern"], RosterPattern.objects.get().pk
        )

    def test_an_instance_place_names_no_pattern(self):
        (result,) = self.apply([{
            "kind": "place", "member": self.member.pk,
            "date": "2026-11-02", "weekly": False,
            "start": "09:00", "end": "17:00",
        }])
        self.assertTrue(result["ok"])
        self.assertNotIn("pattern", result)


class RosterStoreSourceTests(TestCase):
    def test_the_store_runs_the_chain(self):
        src = (STATIC / "roster-store.js").read_text()
        for pin in [
            'document.addEventListener("os:rplay"',
            "routbox",
            "seedData.apply_url",
            # a play chained onto an unacked place waits for
            # the real id rather than guessing
            'rec.pattern.indexOf("tmp_") === 0',
            "idmap[rec.ref] = r.pattern",
            # convergence never overwrites undrained plays
            "if (queuedKeys.length) return;",
            'document.getElementById("roster-seed")',
            "opensalon-roster",
        ]:
            self.assertIn(pin, src)

    def test_the_book_routes_its_gestures_through_the_store(self):
        src = (STATIC / "webui.js").read_text()
        for pin in [
            "if (rbStoreLive()) { rbPlay(fields); return; }",
            'rbBook.addEventListener("submit"',
            "function rbPaintColumn(state)",
            'document.addEventListener("os:rstate"',
            'querySelectorAll(".rb-shift").forEach(rbBindShift)',
        ]:
            self.assertIn(pin, src)
