import datetime

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.upcoming import upcoming_bookings
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def at(day_offset, hour):
    return NOW + datetime.timedelta(days=day_offset, hours=hour - 12)


class UpcomingBookingsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Online Stylist", online_bookable=True
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        self.other_client = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person"
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

    def test_future_bookings_included_ordered_with_row_fields(self):
        later = self._make(at(2, 9))
        sooner = self._make(at(1, 9))
        at_now = self._make(NOW)
        rows = upcoming_bookings(self.salon, self.client, now=NOW)
        self.assertEqual([r.appointment for r in rows], [at_now, sooner, later])
        row = rows[1]
        self.assertEqual(row.staff_display_name, "Online Stylist")
        self.assertEqual(row.service_name, "Haircut")
        self.assertEqual(row.start, sooner.start)
        self.assertEqual(row.end, sooner.end)

    def test_past_bookings_excluded(self):
        self._make(at(-1, 9))
        self._make(NOW - datetime.timedelta(minutes=1))
        self.assertEqual(upcoming_bookings(self.salon, self.client, now=NOW), [])

    def test_cancelled_bookings_excluded(self):
        self._make(at(1, 9), status=Appointment.Status.CANCELLED)
        kept = self._make(at(1, 10), status=Appointment.Status.BOOKED)
        rows = upcoming_bookings(self.salon, self.client, now=NOW)
        self.assertEqual([r.appointment for r in rows], [kept])

    def test_other_clients_excluded(self):
        mine = self._make(at(1, 9))
        self._make(at(1, 10), client=self.other_client)
        rows = upcoming_bookings(self.salon, self.client, now=NOW)
        self.assertEqual([r.appointment for r in rows], [mine])
        other_rows = upcoming_bookings(self.salon, self.other_client, now=NOW)
        self.assertEqual(len(other_rows), 1)
        self.assertEqual(other_rows[0].appointment.client, self.other_client)

    def test_other_salon_excluded(self):
        self._make(at(1, 9))
        self.assertEqual(
            upcoming_bookings(self.other_salon, self.client, now=NOW), []
        )

    def test_snapshot_name_appointment_does_not_crash(self):
        appt = Appointment.objects.create(
            client=self.client,
            staff_member=self.staff,
            service=None,
            service_name="Snapshot Cut",
            start=at(1, 9),
            end=at(1, 9) + datetime.timedelta(minutes=45),
        )
        rows = upcoming_bookings(self.salon, self.client, now=NOW)
        self.assertEqual([r.appointment for r in rows], [appt])
        self.assertEqual(rows[0].service_name, "Snapshot Cut")
        self.assertEqual(rows[0].staff_display_name, "Online Stylist")
        self.assertEqual(rows[0].start, appt.start)
        self.assertEqual(rows[0].end, appt.end)

    def test_none_salon_or_client_returns_empty(self):
        self._make(at(1, 9))
        self.assertEqual(upcoming_bookings(None, self.client, now=NOW), [])
        self.assertEqual(upcoming_bookings(self.salon, None, now=NOW), [])
