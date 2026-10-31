"""Breaks: the empty-space chooser's second face.

A break is blocked-off time inside a stylist's day — placed from
the day book's open-slot popover with a length and the paid /
unpaid toggle. These tests pin the contract: the endpoint
creates and reports the break so the book can paint it at once,
the day book draws it in the stylist's column, the availability
math treats the span as busy (paid or not — the toggle is the
desk's record, not a booking rule), and a break can be taken
back off the book."""

import datetime
import json
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse

from bookings.availability import available_slots
from bookings.models import Break
from webui.tests import WebuiTestBase

TZ = ZoneInfo("America/New_York")
DAY = datetime.date(2026, 11, 2)  # a Monday


def at(hour, minute=0):
    return datetime.datetime.combine(
        DAY, datetime.time(hour, minute), tzinfo=TZ
    )


class BreakEndpointTests(WebuiTestBase):
    def setUp(self):
        super().setUp()
        self.salon.timezone = "America/New_York"
        self.salon.save()

    def post(self, url_name, payload):
        return self.client.post(
            reverse(url_name),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_create_reports_the_break_for_painting(self):
        resp = self.post(
            "webui:daybook_break",
            {
                "staff_member_id": self.member.pk,
                "date": "2026-11-02",
                "time": "12:00",
                "minutes": 45,
                "paid": True,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        br = data["break"]
        self.assertEqual(br["start_min"], 720)
        self.assertEqual(br["minutes"], 45)
        self.assertTrue(br["paid"])
        self.assertEqual(br["label"], "Paid break")
        row = Break.objects.get(pk=br["id"])
        self.assertEqual(row.staff_member_id, self.member.pk)
        self.assertEqual(row.end, at(12, 45))
        self.assertTrue(row.paid)

    def test_unpaid_is_the_honest_default_word(self):
        resp = self.post(
            "webui:daybook_break",
            {
                "staff_member_id": self.member.pk,
                "date": "2026-11-02",
                "time": "15:00",
                "minutes": 15,
                "paid": False,
            },
        )
        self.assertEqual(resp.json()["break"]["label"], "Break")

    def test_unknown_member_and_silly_length_refused(self):
        resp = self.post(
            "webui:daybook_break",
            {
                "staff_member_id": 999999,
                "date": "2026-11-02",
                "time": "12:00",
                "minutes": 30,
                "paid": False,
            },
        )
        self.assertEqual(resp.status_code, 400)
        resp = self.post(
            "webui:daybook_break",
            {
                "staff_member_id": self.member.pk,
                "date": "2026-11-02",
                "time": "12:00",
                "minutes": 2,
                "paid": False,
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Break.objects.count(), 0)

    def test_remove_takes_it_off_the_book(self):
        br = Break.objects.create(
            staff_member=self.member, start=at(12), end=at(13), paid=False
        )
        resp = self.post("webui:daybook_break_remove", {"break_id": br.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Break.objects.count(), 0)


class BreakOnTheBookTests(WebuiTestBase):
    def test_break_renders_in_the_column_with_its_paid_face(self):
        Break.objects.create(
            staff_member=self.member, start=at(12), end=at(13), paid=True
        )
        page = self.client.get(
            reverse("webui:daybook"), {"date": "2026-11-02"}
        )
        html = page.content.decode()
        self.assertIn('data-break="', html)
        self.assertIn("break-block paid", html)
        self.assertIn("Paid break", html)
        # The chooser the empty-space press lands on.
        self.assertIn('id="slotPop"', html)
        self.assertIn('id="slotPopBreak"', html)
        self.assertIn('id="slotPopPaid"', html)


class BreakAvailabilityTests(WebuiTestBase):
    def setUp(self):
        super().setUp()
        # The base fixture's salon sits in UTC; this test reasons
        # in the salon's real zone so pattern, break and answer
        # share one clock.
        self.salon.timezone = "America/New_York"
        self.salon.save()

    def test_a_break_closes_its_span_paid_or_not(self):
        for paid in (False, True):
            Break.objects.all().delete()
            Break.objects.create(
                staff_member=self.member,
                start=at(12),
                end=at(13),
                paid=paid,
            )
            results = available_slots(self.salon, DAY)
            self.assertEqual(len(results), 1)
            spans = [
                (iv.start, iv.end) for iv in results[0].intervals
            ]
            self.assertEqual(
                spans,
                [(at(9), at(12)), (at(13), at(17))],
                f"paid={paid} must block the same",
            )
