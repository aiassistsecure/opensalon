import datetime

from django.test import TestCase

from bookings.availability import available_slots
from bookings.models import Appointment
from clients.models import Client
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
            salon=self.salon, display_name="Stylist One"
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

    def _appt(self, start_h, end_h, staff=None, day=MONDAY, **kw):
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.staff,
            service=self.service, start=at(day, start_h), end=at(day, end_h), **kw,
        )

    def _intervals(self, result, staff=None):
        staff = staff or self.staff
        entry = next(r for r in result if r.staff_member == staff)
        return [(i.start, i.end) for i in entry.intervals]

    def test_roster_window_is_free_when_no_appointments(self):
        self._roster()
        result = available_slots(self.salon, MONDAY)
        self.assertEqual(self._intervals(result), [(at(MONDAY, 9), at(MONDAY, 17))])

    def test_no_roster_that_weekday_means_no_entry(self):
        self._roster(weekday=1)
        self.assertEqual(available_slots(self.salon, MONDAY), [])

    def test_appointment_splits_window(self):
        self._roster()
        self._appt(11, 12)
        self.assertEqual(
            self._intervals(available_slots(self.salon, MONDAY)),
            [(at(MONDAY, 9), at(MONDAY, 11)), (at(MONDAY, 12), at(MONDAY, 17))],
        )

    def test_cancelled_appointment_does_not_subtract(self):
        self._roster()
        self._appt(11, 12, status=Appointment.Status.CANCELLED)
        self.assertEqual(
            self._intervals(available_slots(self.salon, MONDAY)),
            [(at(MONDAY, 9), at(MONDAY, 17))],
        )

    def test_non_cancelled_statuses_subtract(self):
        self._roster()
        self._appt(11, 12, status=Appointment.Status.NO_SHOW)
        self.assertEqual(
            self._intervals(available_slots(self.salon, MONDAY)),
            [(at(MONDAY, 9), at(MONDAY, 11)), (at(MONDAY, 12), at(MONDAY, 17))],
        )

    def test_appointment_clipped_to_roster_edges(self):
        self._roster()
        self._appt(7, 10)
        self._appt(16, 19)
        self.assertEqual(
            self._intervals(available_slots(self.salon, MONDAY)),
            [(at(MONDAY, 10), at(MONDAY, 16))],
        )

    def test_fully_booked_returns_entry_with_no_intervals(self):
        self._roster()
        self._appt(9, 17)
        result = available_slots(self.salon, MONDAY)
        self.assertEqual(self._intervals(result), [])

    def test_overlapping_patterns_and_appointments_merge(self):
        self._roster(end=(13, 0))
        self._roster(start=(12, 0))
        self._appt(10, 11)
        self._appt(10, 12)
        self.assertEqual(
            self._intervals(available_slots(self.salon, MONDAY)),
            [(at(MONDAY, 9), at(MONDAY, 10)), (at(MONDAY, 12), at(MONDAY, 17))],
        )

    def test_online_only_excludes_non_bookable_default_flags_them(self):
        other = StaffMember.objects.create(
            salon=self.salon, display_name="Offline", online_bookable=False
        )
        self._roster(); self._roster(staff=other)
        default = available_slots(self.salon, MONDAY)
        flagged = {r.staff_member: r.online_bookable for r in default}
        self.assertEqual(flagged, {self.staff: True, other: False})
        online = available_slots(self.salon, MONDAY, online_only=True)
        self.assertEqual([r.staff_member for r in online], [self.staff])

    def test_inactive_staff_pattern_and_other_salon_excluded(self):
        inactive = StaffMember.objects.create(
            salon=self.salon, display_name="Inactive", active=False
        )
        other_salon = Salon.objects.create(name="Other")
        outsider = StaffMember.objects.create(salon=other_salon, display_name="Out")
        self._roster(); self._roster(staff=inactive); self._roster(staff=outsider)
        self._roster(start=(18, 0), end=(19, 0), active=False)
        result = available_slots(self.salon, MONDAY)
        self.assertEqual([r.staff_member for r in result], [self.staff])
        self.assertEqual(self._intervals(result), [(at(MONDAY, 9), at(MONDAY, 17))])

    def test_other_staff_and_other_day_appointments_ignored(self):
        other = StaffMember.objects.create(salon=self.salon, display_name="Two")
        self._roster(); self._roster(staff=other)
        self._appt(11, 12, staff=other)
        self._appt(11, 12, day=MONDAY + datetime.timedelta(days=1))
        self.assertEqual(
            self._intervals(available_slots(self.salon, MONDAY)),
            [(at(MONDAY, 9), at(MONDAY, 17))],
        )

    def test_service_filters_intervals_shorter_than_duration(self):
        self._roster(end=(12, 0))
        self._appt(10, 11)  # leaves 60m and 60m
        long_service = Service.objects.create(
            category=self.service.category, name="Long", service_minutes=90
        )
        self.assertEqual(len(available_slots(self.salon, MONDAY)[0].intervals), 2)
        self.assertEqual(
            available_slots(self.salon, MONDAY, service=long_service)[0].intervals, ()
        )
        self.assertEqual(
            len(available_slots(self.salon, MONDAY, service=self.service)), 1
        )
