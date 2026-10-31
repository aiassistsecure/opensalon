import datetime

from django.test import TestCase

from bookings.models import Appointment
from bookings.upcoming import (
    list_upcoming,
    salon_upcoming_appointments,
    upcoming_appointments,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class UpcomingAppointmentsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.other_staff = StaffMember.objects.create(
            salon=self.salon, display_name="Another Stylist"
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        self.start = at(DAY, 0)

    def _appt(self, start, **kw):
        end = kw.pop("end", start + datetime.timedelta(minutes=45))
        return Appointment.objects.create(
            client=kw.pop("client", self.client),
            staff_member=kw.pop("staff_member", self.staff),
            service=kw.pop("service", self.service),
            start=start, end=end, **kw,
        )

    def test_empty_horizon(self):
        result = upcoming_appointments(self.salon, self.start, days=7)
        self.assertEqual(result.total, 0)
        self.assertEqual(result.count, 0)
        self.assertEqual(result.appointments, ())
        self.assertEqual(result.by_day, ())
        self.assertEqual(result.by_staff, ())
        self.assertEqual(result.start, self.start)
        self.assertEqual(result.end, self.start + datetime.timedelta(days=7))
        self.assertEqual(result.days, 7)

    def test_ordered_by_start_and_window_bounds(self):
        late = self._appt(at(DAY, 14))
        early = self._appt(at(DAY, 9))
        self._appt(at(DAY, 8) - datetime.timedelta(days=1))  # before
        self._appt(at(DAY, 9) + datetime.timedelta(days=7))  # at end, out
        self._appt(at(DAY, 10) + datetime.timedelta(days=6))  # last day, in
        result = upcoming_appointments(self.salon, self.start, days=7)
        self.assertEqual(
            [e.appointment_id for e in result.appointments],
            [early.pk, late.pk, result.appointments[2].appointment_id],
        )
        self.assertEqual(result.total, 3)
        self.assertEqual(
            [e.start for e in result.appointments],
            sorted(e.start for e in result.appointments),
        )

    def test_start_is_inclusive_and_default_horizon_is_7_days(self):
        self._appt(self.start)
        self._appt(self.start + datetime.timedelta(days=7))
        result = upcoming_appointments(self.salon, self.start)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.days, 7)

    def test_cancelled_excluded_other_statuses_included(self):
        self._appt(at(DAY, 9), status=Appointment.Status.CANCELLED)
        self._appt(at(DAY, 10), status=Appointment.Status.CONFIRMED)
        self._appt(at(DAY, 11), status=Appointment.Status.NO_SHOW)
        result = upcoming_appointments(self.salon, self.start, days=1)
        self.assertEqual(result.total, 2)
        self.assertEqual(
            {e.status for e in result.appointments},
            {Appointment.Status.CONFIRMED, Appointment.Status.NO_SHOW},
        )

    def test_entries_carry_client_service_and_times(self):
        appt = self._appt(at(DAY, 9))
        (entry,) = upcoming_appointments(self.salon, self.start, days=1).appointments
        self.assertEqual(entry.appointment_id, appt.pk)
        self.assertEqual(entry.client, self.client)
        self.assertEqual(entry.client_id, self.client.pk)
        self.assertEqual(entry.client_display_name, "Test Example")
        self.assertEqual(entry.staff_member, self.staff)
        self.assertEqual(entry.staff_member_id, self.staff.pk)
        self.assertEqual(entry.staff_display_name, "Stylist One")
        self.assertEqual(entry.service_name, "Haircut")
        self.assertEqual(entry.service_category_name, "Hair")
        self.assertEqual(entry.start, at(DAY, 9))
        self.assertEqual(entry.end, at(DAY, 9, 45))
        self.assertEqual(entry.status, Appointment.Status.BOOKED)

    def test_service_none_uses_service_name_snapshot(self):
        self._appt(at(DAY, 9), service=None, service_name="Imported Cut")
        (entry,) = upcoming_appointments(self.salon, self.start, days=1).appointments
        self.assertEqual(entry.service_name, "Imported Cut")
        self.assertEqual(entry.service_category_name, "")

    def test_grouped_by_day_and_staff_with_counts(self):
        nxt = DAY + datetime.timedelta(days=1)
        self._appt(at(DAY, 9))
        self._appt(at(DAY, 11))
        self._appt(at(nxt, 9), staff_member=self.other_staff)
        result = upcoming_appointments(self.salon, self.start, days=7)
        self.assertEqual([g.date for g in result.by_day], [DAY, nxt])
        self.assertEqual([g.count for g in result.by_day], [2, 1])
        self.assertEqual(result.counts_by_day, {DAY: 2, nxt: 1})
        self.assertEqual(
            [g.display_name for g in result.by_staff],
            ["Another Stylist", "Stylist One"],
        )
        self.assertEqual([g.count for g in result.by_staff], [1, 2])
        self.assertEqual(
            result.counts_by_staff,
            {self.other_staff.pk: 1, self.staff.pk: 2},
        )
        staff_group = result.by_staff[1]
        self.assertEqual(staff_group.staff_member, self.staff)
        self.assertEqual(len(staff_group.appointments), 2)
        self.assertEqual(result.by_day[0].day, DAY)

    def test_other_salon_excluded(self):
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        other_staff = StaffMember.objects.create(
            salon=other_salon, display_name="Other Stylist"
        )
        other_client = Client.objects.create(
            salon=other_salon, first_name="Other", last_name="Client"
        )
        self._appt(at(DAY, 9))
        self._appt(at(DAY, 10), client=other_client, staff_member=other_staff)
        result = upcoming_appointments(self.salon, self.start, days=1)
        self.assertEqual(result.total, 1)

    def test_zero_days_and_none_salon_return_empty(self):
        self._appt(at(DAY, 9))
        self.assertEqual(
            upcoming_appointments(self.salon, self.start, days=0).total, 0
        )
        result = upcoming_appointments(None, self.start, days=7)
        self.assertEqual(result.total, 0)
        self.assertEqual(result.appointments, ())

    def test_grouping_uses_salon_local_day(self):
        ny = Salon.objects.create(name="NY Salon", timezone="America/New_York")
        staff = StaffMember.objects.create(salon=ny, display_name="NY")
        client = Client.objects.create(salon=ny, first_name="Ny", last_name="C")
        # 2026-11-02 01:30 UTC is 2026-11-01 20:30 EST.
        start = datetime.datetime(2026, 11, 2, 1, 30, tzinfo=UTC)
        self._appt(start, client=client, staff_member=staff)
        result = upcoming_appointments(
            ny, datetime.datetime(2026, 11, 1, tzinfo=UTC), days=2
        )
        self.assertEqual(result.total, 1)
        self.assertEqual(result.by_day[0].date, datetime.date(2026, 11, 1))

    def test_aliases_agree(self):
        self._appt(at(DAY, 9))
        result = upcoming_appointments(self.salon, self.start, days=3)
        self.assertEqual(
            salon_upcoming_appointments(self.salon, self.start, horizon_days=3),
            result,
        )
        self.assertEqual(
            list_upcoming(self.salon, self.start, days=3), result.appointments
        )
