"""The Roster Book: perpetual patterns, the switch, and instances.

The book renders the pattern onto ANY future week (perpetual).
Placing hours with the switch ON writes the pattern — visible this
week, next week, forever. Switch OFF writes a ShiftOverride that
rules just that date. Flip off behaves the same way.
"""
import datetime

from django.test import Client, TestCase
from django.urls import reverse

from saloncore.models import Salon
from team.models import RosterPattern, ShiftOverride, StaffMember

SAT = datetime.date(2026, 10, 31)
NEXT_SAT = datetime.date(2026, 11, 7)
FAR_SAT = datetime.date(2027, 2, 6)  # fourteen weeks out


class RosterBookTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.salon = Salon.objects.create(name="Mint", timezone="America/New_York")
        self.member = StaffMember.objects.create(
            salon=self.salon, display_name="Dawn Davalos"
        )
        self.pattern = RosterPattern.objects.create(
            staff_member=self.member, weekday=5,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0),
        )
        self.url = reverse("webui:roster")

    def get(self, day):
        return self.client.get(self.url, {"date": day.isoformat()})

    def test_pattern_projects_forever(self):
        html = self.get(FAR_SAT).content.decode()
        self.assertIn("Dawn Davalos", html)
        self.assertIn("9 AM – 5 PM", html)
        self.assertIn("Every week", html)

    def test_place_with_switch_on_writes_the_perpetual_pattern(self):
        self.client.post(self.url, {
            "action": "place", "member": self.member.pk,
            "date": "2026-11-02", "start": "10:00", "end": "13:00",
            "weekly": "on",
        })
        self.assertTrue(RosterPattern.objects.filter(
            staff_member=self.member, weekday=0,
            start_time=datetime.time(10, 0), end_time=datetime.time(13, 0),
        ).exists())
        html = self.get(datetime.date(2026, 12, 7)).content.decode()
        self.assertIn("10 AM – 1 PM", html)

    def test_place_with_switch_off_writes_just_the_instance(self):
        self.client.post(self.url, {
            "action": "place", "member": self.member.pk,
            "date": SAT.isoformat(), "start": "10:00", "end": "14:00",
        })
        self.assertTrue(ShiftOverride.objects.filter(
            staff_member=self.member, date=SAT, is_off=False,
        ).exists())
        html = self.get(SAT).content.decode()
        self.assertIn("10 AM – 2 PM", html)
        self.assertIn("This day only", html)
        self.assertNotIn("9 AM – 5 PM", html)
        next_html = self.get(NEXT_SAT).content.decode()
        self.assertIn("9 AM – 5 PM", next_html)

    def test_flip_off_switch_off_is_an_instance_off(self):
        self.client.post(self.url, {
            "action": "off", "member": self.member.pk,
            "date": SAT.isoformat(), "pattern": self.pattern.pk,
        })
        ov = ShiftOverride.objects.get(staff_member=self.member, date=SAT)
        self.assertTrue(ov.is_off)
        self.assertTrue(RosterPattern.objects.filter(pk=self.pattern.pk).exists())
        self.assertIn("Off — this day only", self.get(SAT).content.decode())
        self.assertIn("9 AM – 5 PM", self.get(NEXT_SAT).content.decode())

    def test_flip_off_switch_on_removes_the_pattern_forever(self):
        self.client.post(self.url, {
            "action": "off", "member": self.member.pk,
            "date": SAT.isoformat(), "pattern": self.pattern.pk, "weekly": "on",
        })
        self.assertFalse(RosterPattern.objects.filter(pk=self.pattern.pk).exists())
        self.assertNotIn("9 AM – 5 PM", self.get(FAR_SAT).content.decode())

    def test_day_book_band_follows_an_off_instance(self):
        # The day book's own context (its staff_columns carry the
        # roster bands): the off instance empties Dawn's band on
        # its date, and the perpetual pattern rules the next week.
        from types import SimpleNamespace

        from webui.views import _day_book_context

        ShiftOverride.objects.create(
            staff_member=self.member, date=SAT, is_off=True
        )

        def shift_label(day):
            ctx = _day_book_context(
                SimpleNamespace(GET={"date": day.isoformat()})
            )
            for col in ctx["staff_columns"]:
                if col["member"].pk == self.member.pk:
                    return col["shift_label"]
            return None

        # No column at all: neither rostered (off instance) nor booked.
        self.assertIsNone(shift_label(SAT))
        self.assertEqual(shift_label(NEXT_SAT), "9 AM – 5 PM")
