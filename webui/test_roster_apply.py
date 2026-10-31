"""The roster apply endpoint: the node's half of the roster
book's store chain.

Roster plays (place / move / off / clear) arrive in bulk and
are applied through the same write cores the roster form
posts use, under the switch law: `weekly` ON writes the
perpetual RosterPattern, OFF writes a ShiftOverride ruling
just that date. Each op is answered on its own — a bad play
never poisons its batch, the day book apply's rule carried
to the roster."""

import datetime
import json

from django.test import TestCase
from django.urls import reverse

from saloncore.models import Salon
from team.models import RosterPattern, ShiftOverride, StaffMember

MONDAY = datetime.date(2026, 11, 2)


class RosterApplyTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint On The Avenue")
        self.member = StaffMember.objects.create(
            display_name="Maribel Gonzalez", salon=self.salon
        )
        self.url = reverse("webui:roster_apply")

    def apply(self, ops):
        resp = self.client.post(
            self.url,
            data=json.dumps({"ops": ops}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()["results"]

    def op(self, **kw):
        base = {
            "kind": "place",
            "member": self.member.pk,
            "date": "2026-11-02",
            "weekly": True,
            "start": "09:00",
            "end": "17:00",
        }
        base.update(kw)
        return base

    def test_place_weekly_writes_the_pattern(self):
        (result,) = self.apply([self.op()])
        self.assertTrue(result["ok"])
        pat = RosterPattern.objects.get(staff_member=self.member)
        self.assertEqual(pat.weekday, MONDAY.weekday())
        self.assertEqual(pat.start_time, datetime.time(9, 0))
        self.assertEqual(ShiftOverride.objects.count(), 0)

    def test_place_instance_writes_the_override(self):
        (result,) = self.apply([self.op(weekly=False)])
        self.assertTrue(result["ok"])
        ov = ShiftOverride.objects.get(staff_member=self.member)
        self.assertFalse(ov.is_off)
        self.assertEqual(ov.date, MONDAY)
        self.assertEqual(RosterPattern.objects.count(), 0)

    def test_move_off_clear_follow_the_switch(self):
        pat = RosterPattern.objects.create(
            staff_member=self.member, weekday=MONDAY.weekday(),
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0),
        )
        (moved,) = self.apply([
            self.op(kind="move", pattern=pat.pk, start="10:00", end="18:00")
        ])
        self.assertTrue(moved["ok"])
        pat.refresh_from_db()
        self.assertEqual(pat.start_time, datetime.time(10, 0))

        (offed,) = self.apply([self.op(kind="off", weekly=False)])
        self.assertTrue(offed["ok"])
        self.assertTrue(
            ShiftOverride.objects.get(staff_member=self.member).is_off
        )
        (cleared,) = self.apply([self.op(kind="clear", weekly=False)])
        self.assertTrue(cleared["ok"])
        self.assertEqual(ShiftOverride.objects.count(), 0)

        (gone,) = self.apply([self.op(kind="off", pattern=pat.pk)])
        self.assertTrue(gone["ok"])
        self.assertEqual(RosterPattern.objects.count(), 0)

    def test_a_bad_op_never_poisons_its_batch(self):
        results = self.apply([
            self.op(member=999999),
            self.op(kind="place", start="17:00", end="09:00"),
            self.op(kind="teleport"),
            self.op(),
        ])
        self.assertEqual(
            [r["ok"] for r in results], [False, False, False, True]
        )
        self.assertEqual(RosterPattern.objects.count(), 1)

    def test_the_form_post_still_speaks_the_same_law(self):
        resp = self.client.post(
            reverse("webui:roster"),
            {
                "action": "place",
                "member": str(self.member.pk),
                "date": "2026-11-02",
                "weekly": "on",
                "start": "09:00",
                "end": "17:00",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(RosterPattern.objects.count(), 1)
