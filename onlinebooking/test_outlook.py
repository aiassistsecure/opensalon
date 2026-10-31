import datetime

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.outlook import (
    DEFAULT_OUTLOOK_DAYS,
    availability_outlook,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class AvailabilityOutlookTests(TestCase):
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
            category=category, name="Haircut", service_minutes=60
        )

    def _roster(self, staff=None, weekday=0, start=(9, 0), end=(11, 0), **kw):
        return RosterPattern.objects.create(
            staff_member=staff or self.staff, weekday=weekday,
            start_time=datetime.time(*start), end_time=datetime.time(*end), **kw,
        )

    def test_counts_slots_over_default_seven_days(self):
        self._roster()  # Mondays 09:00-11:00; 60 min -> 5 starts
        rows = availability_outlook(self.salon, 60, start_date=MONDAY)
        self.assertEqual(DEFAULT_OUTLOOK_DAYS, 7)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.staff_member, self.staff)
        self.assertEqual(row.display_name, "Online Stylist")
        self.assertEqual(row.total_slots, 5)
        self.assertEqual(row.slot_count, 5)
        self.assertEqual(len(row.days), 7)
        self.assertEqual(row.days[0].date, MONDAY)
        self.assertEqual(row.days[0].slot_count, 5)
        self.assertTrue(all(d.slot_count == 0 for d in row.days[1:]))
        self.assertEqual(sum(d.slot_count for d in row.days), row.total_slots)
        self.assertEqual(row.days_with_availability, 1)
        self.assertEqual(row.first_available_date, MONDAY)
        self.assertEqual(row.first_slot, at(MONDAY, 9))
        self.assertEqual(row.days[0].last_slot, at(MONDAY, 10))

    def test_custom_window_includes_second_monday(self):
        self._roster()
        rows = availability_outlook(self.salon, 60, days=8, start_date=MONDAY)
        self.assertEqual(rows[0].total_slots, 10)
        self.assertEqual(rows[0].days_with_availability, 2)
        one = availability_outlook(self.salon, 60, days=1, start_date=MONDAY)
        self.assertEqual(one[0].total_slots, 5)
        self.assertEqual(len(one[0].days), 1)

    def test_accepts_service_and_timedelta_durations(self):
        self._roster()
        by_service = availability_outlook(
            self.salon, self.service, start_date=MONDAY)
        by_delta = availability_outlook(
            self.salon, datetime.timedelta(minutes=60), start_date=MONDAY)
        self.assertEqual(by_service[0].total_slots, 5)
        self.assertEqual(by_delta[0].total_slots, 5)

    def test_toggle_off_and_inactive_staff_are_excluded(self):
        offline = StaffMember.objects.create(
            salon=self.salon, display_name="Offline", online_bookable=False)
        inactive = StaffMember.objects.create(
            salon=self.salon, display_name="Inactive", active=False)
        self._roster()
        self._roster(staff=offline)
        self._roster(staff=inactive)
        rows = availability_outlook(self.salon, 60, start_date=MONDAY)
        self.assertEqual([r.staff_member for r in rows], [self.staff])

    def test_other_salon_staff_are_excluded(self):
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        other = StaffMember.objects.create(
            salon=other_salon, display_name="Other", online_bookable=True)
        self._roster(staff=other)
        self._roster()
        rows = availability_outlook(self.salon, 60, start_date=MONDAY)
        self.assertEqual([r.staff_member for r in rows], [self.staff])

    def test_unrostered_bookable_staff_appears_with_zero(self):
        rows = availability_outlook(self.salon, 60, start_date=MONDAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].total_slots, 0)
        self.assertEqual(rows[0].days_with_availability, 0)
        self.assertIsNone(rows[0].first_available_date)
        self.assertIsNone(rows[0].first_slot)

    def test_existing_appointment_reduces_count(self):
        self._roster(start=(9, 0), end=(17, 0))
        Appointment.objects.create(
            client=self.client, staff_member=self.staff, service=self.service,
            start=at(MONDAY, 11), end=at(MONDAY, 12))
        rows = availability_outlook(self.salon, 60, days=1, start_date=MONDAY)
        # 09:00-17:00 at 15-min steps for 60 min is 29 starts; the
        # 11:00-12:00 appointment removes 10:15..11:45 starts (7).
        self.assertEqual(rows[0].total_slots, 22)

    def test_none_salon_and_non_positive_days_return_empty(self):
        self.assertEqual(availability_outlook(None, 60, start_date=MONDAY), [])
        self.assertEqual(
            availability_outlook(self.salon, 60, days=0, start_date=MONDAY), [])
        self.assertEqual(
            availability_outlook(self.salon, 60, days=-1, start_date=MONDAY), [])

    def test_default_start_date_is_today(self):
        from django.utils import timezone as dj_tz
        today = dj_tz.localdate()
        self._roster(weekday=today.weekday(), start=(9, 0), end=(10, 0))
        rows = availability_outlook(self.salon, 60)
        self.assertEqual(rows[0].days[0].date, today)
        self.assertEqual(rows[0].total_slots, 1)

    def test_read_only_nothing_mutated(self):
        self._roster()
        before = (StaffMember.objects.count(), RosterPattern.objects.count(),
                  Appointment.objects.count())
        availability_outlook(self.salon, 60, start_date=MONDAY)
        after = (StaffMember.objects.count(), RosterPattern.objects.count(),
                 Appointment.objects.count())
        self.assertEqual(before, after)

    def test_non_positive_duration_raises_from_slots_service(self):
        self._roster()
        with self.assertRaises(ValueError):
            availability_outlook(self.salon, 0, start_date=MONDAY)
