import datetime

from django.test import TestCase

from bookings.models import Appointment
from bookings.staff_day import staff_day_load, staff_load_for_day
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC
    )


class StaffDayLoadTests(TestCase):
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

    def _appt(self, start, end, staff=None, **kw):
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.staff,
            service=self.service, start=start, end=end, **kw,
        )

    def test_empty_day_salon_form_lists_staff_with_zero_load(self):
        (load,) = staff_day_load(self.salon, DAY)
        self.assertEqual(load.staff_member, self.staff)
        self.assertEqual(load.staff_member_id, self.staff.pk)
        self.assertEqual(load.display_name, "Stylist One")
        self.assertEqual(load.appointment_count, 0)
        self.assertEqual(load.booked_minutes, 0)
        self.assertIsNone(load.first_start)
        self.assertIsNone(load.last_end)
        self.assertIsNone(load.first_appointment_time)
        self.assertIsNone(load.last_appointment_time)

    def test_empty_day_date_only_form_returns_empty_list(self):
        self.assertEqual(staff_day_load(DAY), [])

    def test_multiple_staff_counts_minutes_and_first_last(self):
        other = StaffMember.objects.create(
            salon=self.salon, display_name="Another Stylist"
        )
        self._appt(at(DAY, 14), at(DAY, 15))
        self._appt(at(DAY, 9), at(DAY, 9, 45))
        self._appt(at(DAY, 11), at(DAY, 12, 30), staff=other)
        loads = staff_day_load(self.salon, DAY)
        self.assertEqual([load.staff_member for load in loads], [other, self.staff])
        other_load, own = loads
        self.assertEqual(other_load.appointment_count, 1)
        self.assertEqual(other_load.booked_minutes, 90)
        self.assertEqual(own.appointment_count, 2)
        self.assertEqual(own.booked_minutes, 105)  # 60 + 45
        self.assertEqual(own.first_start, at(DAY, 9))
        self.assertEqual(own.first_appointment_time, at(DAY, 9))
        self.assertEqual(own.last_start, at(DAY, 14))
        self.assertEqual(own.last_end, at(DAY, 15))
        self.assertEqual(own.last_appointment_time, at(DAY, 15))
        # Date-only form returns the same loads for staff with work.
        self.assertEqual(staff_day_load(DAY), loads)

    def test_cancelled_excluded(self):
        self._appt(at(DAY, 9), at(DAY, 10), status=Appointment.Status.CANCELLED)
        self._appt(at(DAY, 11), at(DAY, 12), status=Appointment.Status.NO_SHOW)
        (load,) = staff_day_load(self.salon, DAY)
        self.assertEqual(load.appointment_count, 1)
        self.assertEqual(load.booked_minutes, 60)
        self.assertEqual(load.first_start, at(DAY, 11))

    def test_minutes_correct_for_partial_hours(self):
        self._appt(at(DAY, 9, 15), at(DAY, 9, 45))  # 30
        self._appt(at(DAY, 10), at(DAY, 11, 15))  # 75
        (load,) = staff_load_for_day(self.salon, DAY)
        self.assertEqual(load.booked_minutes, 105)

    def test_other_day_and_inactive_staff_excluded_in_salon_form(self):
        inactive = StaffMember.objects.create(
            salon=self.salon, display_name="Inactive", active=False
        )
        nxt = DAY + datetime.timedelta(days=1)
        self._appt(at(nxt, 9), at(nxt, 10))
        self._appt(at(DAY, 9), at(DAY, 10), staff=inactive)
        (load,) = staff_day_load(self.salon, DAY)
        self.assertEqual(load.staff_member, self.staff)
        self.assertEqual(load.appointment_count, 0)
