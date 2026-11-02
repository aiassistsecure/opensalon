"""One slot, one booking — the double-confirm pins.

Founder report (2026-11-02): "I can confirm the booking on
/book more than one time for a time slot. I get toasted and
everything." The server was already honest — every repeated
confirm is answered, never duplicated (the variants below) —
but the page's resident availability picture never learned
the booking happened: the just-taken slot stayed lit, so the
guest could walk the whole flow again and be toasted again.
The client half of the law: the moment a confirm answers ok
(fresh or already-yours), the booked span is cut out of the
resident picture (consumeBookedSpan) before the done room
opens, so the slot is dark for any second walk — exactly as
a fresh page load would paint it.
"""
import datetime
from pathlib import Path

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Appointment
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

BOOK_HTML = (
    Path(__file__).resolve().parent / "templates" / "webui" / "book.html"
).read_text()


class DoubleConfirmServerTests(TestCase):
    """The write path answers repeats; it never duplicates."""

    def setUp(self):
        self.salon = Salon.objects.create(
            name="Once Salon", timezone="UTC", currency="USD"
        )
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Cuts"
        )
        self.service = Service.objects.create(
            category=category, name="Signature Cut", service_minutes=60
        )
        self.service2 = Service.objects.create(
            category=category, name="Quick Trim", service_minutes=30
        )
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Dana Stylist"
        )
        self.tomorrow = timezone.now().date() + datetime.timedelta(days=1)
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=self.tomorrow.weekday(),
            start_time=datetime.time(9, 0), end_time=datetime.time(12, 0),
        )

    def confirm(self, **over):
        payload = {
            "service": self.service.pk,
            "staff": self.staff.pk,
            "day": self.tomorrow.isoformat(),
            "time": "9:00",
            "first_name": "Pat",
            "last_name": "Guest",
            "phone": "5550100",
            "email": "pat@example.test",
            "format": "json",
        }
        payload.update(over)
        return self.client.post(reverse("webui:book_confirm"), payload)

    def landed(self):
        return Appointment.objects.filter(staff_member=self.staff).count()

    def test_identical_repeat_answers_already_and_books_once(self):
        first = self.confirm().json()
        self.assertTrue(first["ok"])
        second = self.confirm().json()
        self.assertTrue(second["ok"])
        self.assertTrue(second["already"])
        self.assertEqual(self.landed(), 1)

    def test_second_guest_same_slot_is_refused(self):
        self.confirm()
        second = self.confirm(
            first_name="Other", phone="5559999", email="o@example.test"
        ).json()
        self.assertFalse(second["ok"])
        self.assertEqual(second["error"], "taken")
        self.assertEqual(self.landed(), 1)

    def test_repeat_with_reformatted_phone_stays_one_booking(self):
        self.confirm()
        second = self.confirm(phone="555-0100").json()
        self.assertTrue(second["ok"])
        self.assertTrue(second["already"])
        self.assertEqual(self.landed(), 1)

    def test_other_service_same_start_is_refused(self):
        self.confirm()
        second = self.confirm(service=self.service2.pk).json()
        self.assertFalse(second["ok"])
        self.assertEqual(second["error"], "taken")
        self.assertEqual(self.landed(), 1)

    def test_start_inside_the_booked_span_is_refused(self):
        self.confirm()
        second = self.confirm(time="9:30").json()
        self.assertFalse(second["ok"])
        self.assertEqual(second["error"], "taken")
        self.assertEqual(self.landed(), 1)


class ConsumeBookedSpanPins(TestCase):
    """The resident picture cuts the booked span at confirm."""

    def test_consume_function_exists_and_cuts_free_spans(self):
        self.assertIn("function consumeBookedSpan(fd)", BOOK_HTML)
        body = BOOK_HTML.split("function consumeBookedSpan(fd)")[1]
        body = body.split("\n  }")[0]
        self.assertIn("AVAIL.free[day][staffId] = kept", body)
        self.assertIn("svc.minutes", body)

    def test_consume_runs_on_ok_before_the_done_room(self):
        handler = BOOK_HTML.split('form.addEventListener("submit"')[1]
        ok_at = handler.index("if (body.ok)")
        consume_at = handler.index("consumeBookedSpan(fd)", ok_at)
        done_at = handler.index('go("booked")', ok_at)
        self.assertLess(consume_at, done_at)

    def test_taken_still_refreshes_the_picture(self):
        handler = BOOK_HTML.split('form.addEventListener("submit"')[1]
        self.assertIn('body.error === "taken"', handler)
        self.assertIn("refreshAvailability", handler)
