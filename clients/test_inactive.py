import datetime

from django.test import TestCase

from bookings.models import Appointment
from clients.inactive import (
    DEFAULT_INACTIVE_DAYS,
    InactiveClient,
    inactive_clients,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def at(day_offset, hour=12):
    return NOW + datetime.timedelta(days=day_offset, hours=hour - 12)


class InactiveBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(
            name="Other Salon", timezone="UTC"
        )
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        self._n = 0

    def _client(self, salon=None):
        self._n += 1
        return Client.objects.create(
            salon=salon or self.salon,
            first_name="Client",
            last_name=f"{self._n:03d}",
        )

    def _appt(self, client, start, **kw):
        return Appointment.objects.create(
            client=client,
            staff_member=self.staff,
            service=self.service,
            start=start,
            end=start + datetime.timedelta(minutes=45),
            **kw,
        )

    def _ids(self, rows):
        return [row.client_id for row in rows]


class ThresholdTests(InactiveBase):
    def test_default_threshold_is_90_days(self):
        self.assertEqual(DEFAULT_INACTIVE_DAYS, 90)
        recent = self._client()
        stale = self._client()
        self._appt(recent, at(-89))
        self._appt(stale, at(-91))
        rows = inactive_clients(salon=self.salon, now=NOW)
        self.assertEqual(self._ids(rows), [stale.pk])

    def test_visit_exactly_at_threshold_is_not_inactive(self):
        client = self._client()
        self._appt(client, at(-90))
        rows = inactive_clients(salon=self.salon, days=90, now=NOW)
        self.assertEqual(rows, [])

    def test_visit_just_beyond_threshold_is_inactive(self):
        client = self._client()
        appt = self._appt(client, at(-91))
        rows = inactive_clients(salon=self.salon, days=90, now=NOW)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIsInstance(row, InactiveClient)
        self.assertEqual(row.client_id, client.pk)
        self.assertEqual(row.client, client)
        self.assertEqual(row.last_appointment, appt.start)
        self.assertEqual(row.last_appointment_date, appt.start.date())
        self.assertEqual(row.last_visit_date, appt.start.date())
        self.assertEqual(row.days_since_last_visit, 91)
        self.assertEqual(row.days_since, 91)

    def test_recent_visit_is_not_inactive(self):
        client = self._client()
        self._appt(client, at(-1))
        self.assertEqual(inactive_clients(salon=self.salon, now=NOW), [])

    def test_custom_threshold(self):
        client = self._client()
        self._appt(client, at(-30))
        self.assertEqual(
            inactive_clients(salon=self.salon, days=60, now=NOW), []
        )
        rows = inactive_clients(salon=self.salon, days=14, now=NOW)
        self.assertEqual(self._ids(rows), [client.pk])
        self.assertEqual(rows[0].days_since_last_visit, 30)

    def test_last_visit_is_most_recent_non_cancelled(self):
        client = self._client()
        self._appt(client, at(-200))
        latest = self._appt(client, at(-100))
        rows = inactive_clients(salon=self.salon, days=90, now=NOW)
        self.assertEqual(rows[0].last_appointment, latest.start)
        self.assertEqual(rows[0].days_since_last_visit, 100)

    def test_invalid_days_raise(self):
        with self.assertRaises(ValueError):
            inactive_clients(salon=self.salon, days=-1, now=NOW)
        with self.assertRaises(ValueError):
            inactive_clients(salon=self.salon, days="90", now=NOW)


class NeverBookedAndCancelledTests(InactiveBase):
    def test_never_booked_client_is_inactive_with_nones(self):
        client = self._client()
        rows = inactive_clients(salon=self.salon, now=NOW)
        self.assertEqual(self._ids(rows), [client.pk])
        self.assertIsNone(rows[0].last_appointment)
        self.assertIsNone(rows[0].last_appointment_date)
        self.assertIsNone(rows[0].days_since_last_visit)

    def test_cancelled_only_client_counts_as_never_visited(self):
        client = self._client()
        self._appt(client, at(-5), status=Appointment.Status.CANCELLED)
        self._appt(client, at(-200), status=Appointment.Status.CANCELLED)
        rows = inactive_clients(salon=self.salon, now=NOW)
        self.assertEqual(self._ids(rows), [client.pk])
        self.assertIsNone(rows[0].last_appointment_date)
        self.assertIsNone(rows[0].days_since_last_visit)

    def test_recent_cancelled_does_not_mask_old_visit(self):
        client = self._client()
        old = self._appt(client, at(-120))
        self._appt(client, at(-2), status=Appointment.Status.CANCELLED)
        rows = inactive_clients(salon=self.salon, now=NOW)
        self.assertEqual(self._ids(rows), [client.pk])
        self.assertEqual(rows[0].last_appointment, old.start)
        self.assertEqual(rows[0].days_since_last_visit, 120)

    def test_future_only_client_has_no_last_visit(self):
        client = self._client()
        self._appt(client, at(10))
        rows = inactive_clients(salon=self.salon, now=NOW)
        self.assertEqual(self._ids(rows), [client.pk])
        self.assertIsNone(rows[0].last_appointment_date)

    def test_non_cancelled_statuses_count_as_visits(self):
        for status in (
            Appointment.Status.BOOKED,
            Appointment.Status.COMPLETED,
            Appointment.Status.NO_SHOW,
        ):
            client = self._client()
            self._appt(client, at(-1), status=status)
        self.assertEqual(inactive_clients(salon=self.salon, now=NOW), [])


class OrderingAndScopeTests(InactiveBase):
    def test_ordering_never_booked_first_then_oldest_visit(self):
        oldest = self._client()
        never = self._client()
        newer_stale = self._client()
        self._appt(oldest, at(-200))
        self._appt(newer_stale, at(-100))
        rows = inactive_clients(salon=self.salon, now=NOW)
        self.assertEqual(
            self._ids(rows), [never.pk, oldest.pk, newer_stale.pk]
        )
        self.assertEqual(
            [row.days_since_last_visit for row in rows], [None, 200, 100]
        )

    def test_ordering_tie_breaks_on_client_id(self):
        first = self._client()
        second = self._client()
        self._appt(second, at(-100))
        self._appt(first, at(-100))
        rows = inactive_clients(salon=self.salon, now=NOW)
        self.assertEqual(self._ids(rows), [first.pk, second.pk])

    def test_salon_scope_excludes_other_salons(self):
        mine = self._client()
        theirs = self._client(salon=self.other_salon)
        rows = inactive_clients(salon=self.salon, now=NOW)
        self.assertEqual(self._ids(rows), [mine.pk])
        rows = inactive_clients(salon=self.other_salon, now=NOW)
        self.assertEqual(self._ids(rows), [theirs.pk])

    def test_no_salon_reports_all_clients(self):
        mine = self._client()
        theirs = self._client(salon=self.other_salon)
        rows = inactive_clients(now=NOW)
        self.assertEqual(set(self._ids(rows)), {mine.pk, theirs.pk})

    def test_other_clients_appointments_do_not_count(self):
        client = self._client()
        other = self._client()
        self._appt(other, at(-1))
        rows = inactive_clients(salon=self.salon, now=NOW)
        self.assertEqual(self._ids(rows), [client.pk])

    def test_report_is_read_only(self):
        client = self._client()
        self._appt(client, at(-100))
        before = (Client.objects.count(), Appointment.objects.count())
        inactive_clients(salon=self.salon, now=NOW)
        after = (Client.objects.count(), Appointment.objects.count())
        self.assertEqual(before, after)
