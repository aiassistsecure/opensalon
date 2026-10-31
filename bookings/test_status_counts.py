import datetime

from django.test import TestCase

from bookings.models import Appointment
from bookings.status_counts import (
    appointment_status_counts,
    status_counts,
    status_counts_for_day,
    status_counts_for_range,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC
    )


class AppointmentStatusCountsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )

    def _appt(self, start, status=Appointment.Status.BOOKED, **kw):
        end = kw.pop("end", start + datetime.timedelta(minutes=45))
        return Appointment.objects.create(
            client=kw.pop("client", self.client),
            staff_member=kw.pop("staff_member", self.staff),
            service=kw.pop("service", self.service),
            start=start, end=end, status=status, **kw,
        )

    def test_empty_day_all_statuses_present_with_zero(self):
        result = appointment_status_counts(self.salon, DAY)
        self.assertEqual(result.total, 0)
        self.assertEqual(result.salon, self.salon)
        self.assertEqual(result.start_date, DAY)
        self.assertEqual(result.end_date, DAY)
        self.assertEqual(result.date, DAY)
        for value, _label in Appointment.Status.choices:
            self.assertEqual(result.by_status[value], 0)
            self.assertEqual(result[value], 0)
            self.assertEqual(result.count_for(value), 0)
        self.assertEqual(result.counts, result.by_status)
        self.assertEqual(result.as_dict()["total"], 0)

    def test_counts_by_status_plus_total(self):
        self._appt(at(DAY, 9), Appointment.Status.BOOKED)
        self._appt(at(DAY, 10), Appointment.Status.BOOKED)
        self._appt(at(DAY, 11), Appointment.Status.CONFIRMED)
        self._appt(at(DAY, 12), Appointment.Status.COMPLETED)
        self._appt(at(DAY, 13), Appointment.Status.CANCELLED)
        self._appt(at(DAY, 14), Appointment.Status.NO_SHOW)
        result = appointment_status_counts(self.salon, DAY)
        self.assertEqual(result.total, 6)
        self.assertEqual(result.booked, 2)
        self.assertEqual(result.confirmed, 1)
        self.assertEqual(result.completed, 1)
        self.assertEqual(result.cancelled, 1)
        self.assertEqual(result.no_show, 1)
        self.assertEqual(result.arrived, 0)
        self.assertEqual(result.in_service, 0)
        self.assertEqual(sum(result.by_status.values()), result.total)

    def test_every_status_value_counts(self):
        for i, (value, _label) in enumerate(Appointment.Status.choices):
            self._appt(at(DAY, 8 + i), value)
        result = status_counts_for_day(self.salon, DAY)
        self.assertEqual(result.total, len(Appointment.Status.choices))
        for value, _label in Appointment.Status.choices:
            self.assertEqual(result.by_status[value], 1)

    def test_other_day_and_other_salon_excluded(self):
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        other_staff = StaffMember.objects.create(
            salon=other_salon, display_name="Other Stylist"
        )
        other_client = Client.objects.create(
            salon=other_salon, first_name="Other", last_name="Client"
        )
        self._appt(at(DAY, 9))
        self._appt(at(DAY + datetime.timedelta(days=1), 9))
        self._appt(at(DAY, 10), client=other_client, staff_member=other_staff)
        result = appointment_status_counts(self.salon, DAY)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.booked, 1)

    def test_date_range_is_inclusive(self):
        nxt = DAY + datetime.timedelta(days=1)
        last = DAY + datetime.timedelta(days=2)
        self._appt(at(DAY, 9), Appointment.Status.BOOKED)
        self._appt(at(nxt, 9), Appointment.Status.COMPLETED)
        self._appt(at(last, 9), Appointment.Status.COMPLETED)
        self._appt(at(last + datetime.timedelta(days=1), 9))
        result = appointment_status_counts(self.salon, DAY, last)
        self.assertEqual(result.total, 3)
        self.assertEqual(result.booked, 1)
        self.assertEqual(result.completed, 2)
        self.assertEqual(result.start_date, DAY)
        self.assertEqual(result.end_date, last)
        # Keyword and alias forms agree.
        self.assertEqual(
            appointment_status_counts(
                self.salon, date_from=DAY, date_to=last
            ),
            result,
        )
        self.assertEqual(status_counts_for_range(self.salon, DAY, last), result)
        self.assertEqual(status_counts(self.salon, DAY, last), result)
        # Single day inside the range.
        self.assertEqual(status_counts_for_day(self.salon, nxt).total, 1)

    def test_reversed_range_returns_zeros(self):
        self._appt(at(DAY, 9))
        result = appointment_status_counts(
            self.salon, DAY + datetime.timedelta(days=1), DAY
        )
        self.assertEqual(result.total, 0)
        self.assertEqual(result.booked, 0)

    def test_none_salon_returns_zeros(self):
        self._appt(at(DAY, 9))
        result = appointment_status_counts(None, DAY)
        self.assertEqual(result.total, 0)
        self.assertEqual(result.booked, 0)

    def test_service_none_appointment_still_counts(self):
        self._appt(at(DAY, 9), service=None, service_name="Imported Cut")
        result = appointment_status_counts(self.salon, DAY)
        self.assertEqual(result.total, 1)

    def test_local_date_uses_salon_timezone(self):
        ny = Salon.objects.create(
            name="NY Salon", timezone="America/New_York"
        )
        staff = StaffMember.objects.create(salon=ny, display_name="NY")
        client = Client.objects.create(
            salon=ny, first_name="Ny", last_name="Client"
        )
        # 2026-11-02 01:30 UTC is 2026-11-01 20:30 EST (UTC-5).
        start = datetime.datetime(2026, 11, 2, 1, 30, tzinfo=UTC)
        self._appt(start, client=client, staff_member=staff)
        prev = datetime.date(2026, 11, 1)
        self.assertEqual(appointment_status_counts(ny, prev).total, 1)
        self.assertEqual(appointment_status_counts(ny, DAY).total, 0)
        # A datetime argument is reduced to its salon-local date.
        self.assertEqual(appointment_status_counts(ny, start).total, 1)

    def test_spanning_midnight_counts_on_start_day_only(self):
        start = at(DAY, 23, 30)
        end = at(DAY + datetime.timedelta(days=1), 0, 30)
        self._appt(start, end=end)
        self.assertEqual(appointment_status_counts(self.salon, DAY).total, 1)
        nxt = DAY + datetime.timedelta(days=1)
        self.assertEqual(appointment_status_counts(self.salon, nxt).total, 0)
