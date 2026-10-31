"""Store law: what the client writes, it keeps — HTTP recovers.

The founder's two-stage design, daybook slice (2026-10-31): the
embedded NEDB is the state machine; a booking's reply carries the
new appointment's pack entry home so the store adopts it as a doc
with no pack re-fetch. The entry must be the pack's own entry —
built by the day book's context builder, it cannot disagree with
the pack about a block, a price, or a visit.
"""
import datetime
import json
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client as SalonClient
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import RosterPattern, StaffMember


class StoreLawTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.salon = Salon.objects.create(name="Mint On The Avenue")
        self.level = StaffLevel.objects.create(
            name="Level 6", salon=self.salon
        )
        category = ServiceCategory.objects.create(
            name="Hair", salon=self.salon
        )
        self.service = Service.objects.create(
            name="Women's Haircut", category=category, service_minutes=60
        )
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"),
        )
        self.member = StaffMember.objects.create(
            display_name="Maribel Gonzalez", salon=self.salon,
            staff_level=self.level,
        )
        RosterPattern.objects.create(
            staff_member=self.member,
            weekday=RosterPattern.Weekday.MONDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
        self.person = SalonClient.objects.create(
            salon=self.salon, first_name="Jaime", last_name="Orta",
            phone="407-555-0100",
        )
        # A past visit, so the booking below is not his first —
        # a first-ever visit is exactly what is_new means.
        past = timezone.make_aware(datetime.datetime(2026, 10, 5, 10, 0))
        Appointment.objects.create(
            client=self.person, staff_member=self.member,
            service=self.service, start=past,
            end=past + datetime.timedelta(hours=1), status="completed",
        )
        self.book_url = reverse("webui:daybook_book")

    def book(self, **extra):
        payload = {
            "client_id": self.person.pk,
            "staff_member_id": self.member.pk,
            "service_id": self.service.pk,
            "date": "2026-11-02",
            "time": "10:00",
        }
        payload.update(extra)
        resp = self.client.post(
            self.book_url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_booking_reply_carries_the_pack_entry(self):
        data = self.book()
        entry = data["entry"]
        self.assertIsNotNone(entry)
        self.assertEqual(entry["id"], data["appointment_id"])
        self.assertEqual(entry["client"], "Jaime Orta")
        self.assertEqual(entry["service"], "Women's Haircut")
        self.assertEqual(entry["staff_id"], self.member.pk)
        self.assertEqual(entry["start_min"], 600)
        self.assertEqual(entry["end_min"], 660)
        self.assertEqual(entry["status"], "booked")
        self.assertEqual(entry["price_label"], "$85")
        self.assertEqual(entry["visit"], data["appointment_id"])
        self.assertFalse(entry["is_new"])

    def test_entry_is_the_pack_entry_key_for_key(self):
        data = self.book()
        pack = self.client.get(
            reverse("webui:daybook_pack"), {"date": "2026-11-02"}
        ).json()
        packed = [
            e for e in pack["days"]["2026-11-02"]
            if e["id"] == data["appointment_id"]
        ]
        self.assertEqual(len(packed), 1)
        self.assertEqual(packed[0], data["entry"])

    def test_new_client_booking_entry_marks_the_guest_new(self):
        data = self.book(
            client_id=None,
            new_client={
                "first_name": "Robin", "last_name": "Voss",
                "phone": "407-555-0199",
            },
        )
        self.assertTrue(data["entry"]["is_new"])
        self.assertEqual(data["entry"]["client"], "Robin Voss")
        appt = Appointment.objects.get(pk=data["appointment_id"])
        self.assertEqual(appt.client.first_name, "Robin")

    def test_shadow_store_accepts_a_put_doc(self):
        # The shell wires the store's events: shadow.js carries
        # the os:put adoption path the booked handler speaks.
        from django.contrib.staticfiles import finders
        with open(finders.find("webui/shadow.js"), encoding="utf-8") as fh:
            shadow = fh.read()
        self.assertIn('"os:put"', shadow)
        self.assertIn('"appointments"', shadow)
