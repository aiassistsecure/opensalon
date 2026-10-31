import datetime

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.slots import available_slots
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class AvailableSlotsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
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

    def _roster(self, staff=None, weekday=0, start=(9, 0), end=(17, 0), **kw):
        return RosterPattern.objects.create(
            staff_member=staff or self.staff, weekday=weekday,
            start_time=datetime.time(*start), end_time=datetime.time(*end), **kw,
        )

    def _appt(self, staff=None, start=None, end=None, **kw):
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.staff,
            service=self.service, start=start, end=end, **kw,
        )

    def test_steps_every_15_minutes_and_service_must_fit(self):
        self._roster(start=(9, 0), end=(11, 0))
        self.assertEqual(
            available_slots(self.staff, MONDAY, 60),
            [at(MONDAY, 9), at(MONDAY, 9, 15), at(MONDAY, 9, 30),
             at(MONDAY, 9, 45), at(MONDAY, 10)],
        )

    def test_accepts_timedelta_and_service_durations(self):
        self._roster(start=(9, 0), end=(11, 0))
        expected = available_slots(self.staff, MONDAY, 45)
        self.assertEqual(
            available_slots(self.staff, MONDAY, datetime.timedelta(minutes=45)),
            expected,
        )
        self.assertEqual(available_slots(self.staff, MONDAY, self.service), expected)
        self.assertEqual(expected[-1], at(MONDAY, 10, 15))

    def test_toggle_off_staff_returns_empty(self):
        offline = StaffMember.objects.create(
            salon=self.salon, display_name="Offline", online_bookable=False
        )
        self._roster(staff=offline)
        self.assertEqual(available_slots(offline, MONDAY, 45), [])

    def test_inactive_staff_returns_empty(self):
        inactive = StaffMember.objects.create(
            salon=self.salon, display_name="Inactive", active=False
        )
        self._roster(staff=inactive)
        self.assertEqual(available_slots(inactive, MONDAY, 45), [])

    def test_unrostered_and_wrong_weekday_return_empty(self):
        self.assertEqual(available_slots(self.staff, MONDAY, 45), [])
        self._roster(weekday=1)
        self.assertEqual(available_slots(self.staff, MONDAY, 45), [])

    def test_existing_appointment_is_subtracted(self):
        self._roster()
        self._appt(start=at(MONDAY, 11), end=at(MONDAY, 11, 45))
        result = available_slots(self.staff, MONDAY, 45)
        # Last start before the appointment ends by 11:00; stepping
        # restarts at the interval start after it (11:45).
        self.assertIn(at(MONDAY, 10, 15), result)
        self.assertNotIn(at(MONDAY, 10, 30), result)
        self.assertNotIn(at(MONDAY, 11), result)
        self.assertIn(at(MONDAY, 11, 45), result)
        self.assertEqual(result, sorted(result))

    def test_cancelled_appointment_does_not_block(self):
        self._roster(start=(9, 0), end=(10, 0))
        self._appt(start=at(MONDAY, 9), end=at(MONDAY, 10),
                   status=Appointment.Status.CANCELLED)
        self.assertEqual(
            available_slots(self.staff, MONDAY, 60), [at(MONDAY, 9)]
        )

    def test_other_staff_appointment_is_ignored(self):
        other = StaffMember.objects.create(
            salon=self.salon, display_name="Other", online_bookable=True
        )
        self._roster(start=(9, 0), end=(10, 0))
        self._roster(staff=other, start=(9, 0), end=(10, 0))
        self._appt(staff=other, start=at(MONDAY, 9), end=at(MONDAY, 10))
        self.assertEqual(
            available_slots(self.staff, MONDAY, 60), [at(MONDAY, 9)]
        )
        self.assertEqual(available_slots(other, MONDAY, 60), [])

    def test_service_longer_than_any_interval_returns_empty(self):
        self._roster(start=(9, 0), end=(10, 0))
        self.assertEqual(available_slots(self.staff, MONDAY, 61), [])

    def test_non_positive_duration_raises(self):
        self._roster()
        with self.assertRaises(ValueError):
            available_slots(self.staff, MONDAY, 0)
        with self.assertRaises(ValueError):
            available_slots(self.staff, MONDAY, datetime.timedelta(minutes=-5))
