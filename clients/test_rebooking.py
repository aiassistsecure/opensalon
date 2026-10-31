import datetime

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from clients.rebooking import (
    DEFAULT_LOOKBACK_DAYS,
    RebookingCandidate,
    rebooking_candidates,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
REF = datetime.date(2026, 11, 2)


def at(day_offset, hour=12):
    return datetime.datetime.combine(
        REF + datetime.timedelta(days=day_offset),
        datetime.time(hour, 0),
        tzinfo=UTC,
    )


class RebookingBase(TestCase):
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
        kw.setdefault("status", Appointment.Status.COMPLETED)
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

    def _candidates(self, **kw):
        kw.setdefault("reference_date", REF)
        kw.setdefault("lookback_days", 42)
        return rebooking_candidates(self.salon, **kw)


class QualificationTests(RebookingBase):
    def test_in_window_completed_visit_qualifies(self):
        client = self._client()
        appt = self._appt(client, at(-20))
        rows = self._candidates()
        self.assertEqual(self._ids(rows), [client.pk])
        row = rows[0]
        self.assertIsInstance(row, RebookingCandidate)
        self.assertEqual(row.client, client)
        self.assertEqual(row.last_visit, appt.start)
        self.assertEqual(row.last_visit_date, appt.start.date())
        self.assertEqual(row.days_since_last_visit, 20)

    def test_no_visit_and_too_old_visit_do_not_qualify(self):
        self._client()
        old = self._client()
        self._appt(old, at(-100))
        recent_outside = self._client()
        self._appt(recent_outside, at(-43))
        self.assertEqual(self._candidates(), [])

    def test_only_completed_visits_count(self):
        client = self._client()
        self._appt(client, at(-10), status=Appointment.Status.NO_SHOW)
        self._appt(client, at(-5), status=Appointment.Status.BOOKED)
        self.assertEqual(self._candidates(), [])

    def test_most_recent_completed_visit_is_used(self):
        client = self._client()
        self._appt(client, at(-100))
        latest = self._appt(client, at(-10))
        rows = self._candidates()
        self.assertEqual(rows[0].last_visit, latest.start)
        self.assertEqual(rows[0].days_since_last_visit, 10)


class FutureBookingTests(RebookingBase):
    def test_future_booking_excludes(self):
        client = self._client()
        self._appt(client, at(-20))
        self._appt(client, at(14), status=Appointment.Status.BOOKED)
        self.assertEqual(self._candidates(), [])

    def test_future_confirmed_booking_excludes(self):
        client = self._client()
        self._appt(client, at(-20))
        self._appt(client, at(1), status=Appointment.Status.CONFIRMED)
        self.assertEqual(self._candidates(), [])

    def test_future_cancelled_booking_does_not_exclude(self):
        client = self._client()
        self._appt(client, at(-20))
        self._appt(client, at(14), status=Appointment.Status.CANCELLED)
        self.assertEqual(self._ids(self._candidates()), [client.pk])


class CancelledVisitTests(RebookingBase):
    def test_cancelled_visit_does_not_count(self):
        client = self._client()
        self._appt(client, at(-10), status=Appointment.Status.CANCELLED)
        self.assertEqual(self._candidates(), [])

    def test_cancelled_recent_visit_falls_back_to_completed(self):
        client = self._client()
        completed = self._appt(client, at(-30))
        self._appt(client, at(-5), status=Appointment.Status.CANCELLED)
        rows = self._candidates()
        self.assertEqual(self._ids(rows), [client.pk])
        self.assertEqual(rows[0].last_visit, completed.start)


class ScopeAndBoundaryTests(RebookingBase):
    def test_other_salon_excluded(self):
        mine = self._client()
        self._appt(mine, at(-20))
        other = self._client(salon=self.other_salon)
        self._appt(other, at(-20))
        self.assertEqual(self._ids(self._candidates()), [mine.pk])
        other_rows = rebooking_candidates(
            self.other_salon, reference_date=REF, lookback_days=42
        )
        self.assertEqual(self._ids(other_rows), [other.pk])

    def test_window_boundaries_are_inclusive(self):
        at_start = self._client()
        self._appt(at_start, at(-42))
        at_ref = self._client()
        self._appt(at_ref, at(0))
        just_outside = self._client()
        self._appt(just_outside, at(-43))
        rows = self._candidates()
        self.assertEqual(self._ids(rows), [at_start.pk, at_ref.pk])

    def test_custom_window(self):
        client = self._client()
        self._appt(client, at(-20))
        self.assertEqual(self._candidates(lookback_days=14), [])
        self.assertEqual(
            self._ids(self._candidates(lookback_days=21)), [client.pk]
        )

    def test_datetime_reference(self):
        client = self._client()
        self._appt(client, at(-20))
        ref_dt = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
        rows = rebooking_candidates(
            self.salon, reference_date=ref_dt, lookback_days=42
        )
        self.assertEqual(self._ids(rows), [client.pk])

    def test_default_window_constant(self):
        self.assertEqual(DEFAULT_LOOKBACK_DAYS, 42)

    def test_invalid_window_raises(self):
        with self.assertRaises(ValueError):
            self._candidates(lookback_days=-1)


class OrderingTests(RebookingBase):
    def test_ordered_by_last_visit_ascending(self):
        newest = self._client()
        self._appt(newest, at(-5))
        oldest = self._client()
        self._appt(oldest, at(-40))
        middle = self._client()
        self._appt(middle, at(-20))
        rows = self._candidates()
        self.assertEqual(
            self._ids(rows), [oldest.pk, middle.pk, newest.pk]
        )

    def test_tie_break_by_client_id(self):
        first = self._client()
        self._appt(first, at(-20))
        second = self._client()
        self._appt(second, at(-20))
        self.assertEqual(self._ids(self._candidates()), [first.pk, second.pk])
