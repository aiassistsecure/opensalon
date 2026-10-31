import datetime

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.history import DEFAULT_HISTORY_LIMIT, past_bookings
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def at(day_offset, hour):
    return NOW + datetime.timedelta(days=day_offset, hours=hour - 12)


class PastBookingsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Online Stylist", online_bookable=True
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )

    def _make(self, start, client=None, staff=None, **kw):
        kw.setdefault("service", self.service)
        return Appointment.objects.create(
            client=client or self.client,
            staff_member=staff or self.staff,
            start=start,
            end=start + datetime.timedelta(minutes=45),
            **kw,
        )

    def test_empty_when_no_bookings(self):
        self.assertEqual(past_bookings(self.salon, self.client, now=NOW), [])
        self.assertEqual(past_bookings(None, self.client, now=NOW), [])
        self.assertEqual(past_bookings(self.salon, None, now=NOW), [])

    def test_past_only_future_and_exactly_now_excluded(self):
        past = self._make(at(-1, 9))
        self._make(at(1, 9))
        self._make(NOW)
        rows = past_bookings(self.salon, self.client, now=NOW)
        self.assertEqual([r.appointment for r in rows], [past])
        self.assertEqual(rows[0].staff_display_name, "Online Stylist")
        self.assertEqual(rows[0].service_name, "Haircut")
        self.assertEqual(rows[0].start, past.start)
        self.assertEqual(rows[0].end, past.end)

    def test_cancelled_included_and_flagged(self):
        cancelled = self._make(
            at(-1, 9), status=Appointment.Status.CANCELLED
        )
        kept = self._make(at(-2, 9), status=Appointment.Status.COMPLETED)
        rows = past_bookings(self.salon, self.client, now=NOW)
        self.assertEqual([r.appointment for r in rows], [cancelled, kept])
        self.assertTrue(rows[0].is_cancelled)
        self.assertTrue(rows[0].cancelled)
        self.assertFalse(rows[1].is_cancelled)
        self.assertFalse(rows[1].cancelled)

    def test_ordering_newest_first(self):
        oldest = self._make(at(-3, 9))
        newest = self._make(at(-1, 9))
        middle = self._make(at(-2, 9))
        rows = past_bookings(self.salon, self.client, now=NOW)
        self.assertEqual(
            [r.appointment for r in rows], [newest, middle, oldest]
        )

    def test_limit_respected(self):
        for offset in range(1, 5):
            self._make(at(-offset, 9))
        rows = past_bookings(self.salon, self.client, now=NOW, limit=2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].start, at(-1, 9))
        self.assertEqual(
            past_bookings(self.salon, self.client, now=NOW, limit=0), []
        )
        self.assertEqual(
            len(past_bookings(self.salon, self.client, now=NOW, limit=None)),
            4,
        )
        self.assertGreater(DEFAULT_HISTORY_LIMIT, 0)

    def test_default_limit_applies(self):
        for offset in range(1, DEFAULT_HISTORY_LIMIT + 3):
            self._make(at(-offset, 9))
        rows = past_bookings(self.salon, self.client, now=NOW)
        self.assertEqual(len(rows), DEFAULT_HISTORY_LIMIT)

    def test_other_salon_excluded(self):
        self._make(at(-1, 9))
        self.assertEqual(
            past_bookings(self.other_salon, self.client, now=NOW), []
        )
