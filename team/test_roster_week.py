import datetime

from django.test import TestCase

from saloncore.models import Salon
from team.models import RosterPattern, StaffMember
from team.roster_week import roster_week, staff_roster_week

MONDAY = datetime.date(2026, 11, 2)  # a Monday
SUNDAY = datetime.date(2026, 11, 8)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class RosterWeekTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )

    def _pattern(self, staff=None, weekday=0, start=(9, 0), end=(17, 0), **kw):
        return RosterPattern.objects.create(
            staff_member=staff or self.staff, weekday=weekday,
            start_time=datetime.time(*start), end_time=datetime.time(*end), **kw,
        )

    def test_week_spans_monday_to_sunday_with_seven_days_per_staff(self):
        self._pattern(weekday=0)
        self._pattern(weekday=6, start=(10, 0), end=(14, 0))
        result = roster_week(self.salon, MONDAY)
        self.assertEqual(result.week_start, MONDAY)
        self.assertEqual(result.week_end, SUNDAY)
        self.assertEqual(result.days[0], MONDAY)
        self.assertEqual(result.days[-1], SUNDAY)
        self.assertEqual(len(result), 1)
        entry = result.entries[0]
        self.assertEqual([d.day for d in entry.days],
                         [MONDAY + datetime.timedelta(days=i) for i in range(7)])
        self.assertEqual(entry.days[0].intervals[0].start, at(MONDAY, 9))
        self.assertEqual(entry.days[6].intervals[0].start, at(SUNDAY, 10))
        self.assertEqual(entry.total_minutes, 480 + 240)
        self.assertEqual(entry.working_days, 2)
        self.assertTrue(entry.is_working)

    def test_non_monday_and_datetime_inputs_snap_to_monday(self):
        wednesday = MONDAY + datetime.timedelta(days=2)
        self.assertEqual(roster_week(self.salon, wednesday).week_start, MONDAY)
        stamp = at(wednesday, 12, 0)
        self.assertEqual(roster_week(self.salon, stamp).week_start, MONDAY)

    def test_off_days_empty_and_split_shift_preserved(self):
        self._pattern(weekday=2, end=(12, 0))
        self._pattern(weekday=2, start=(13, 0))
        entry = roster_week(self.salon, MONDAY).entries[0]
        self.assertFalse(entry.days[0].is_working)
        self.assertEqual(len(entry.days[2].intervals), 2)
        self.assertEqual(entry.days[2].total_minutes, 180 + 240)

    def test_online_bookable_flag_per_staff_and_not_a_filter(self):
        offline = StaffMember.objects.create(
            salon=self.salon, display_name="Offline", online_bookable=False
        )
        self._pattern(); self._pattern(staff=offline)
        result = roster_week(self.salon, MONDAY)
        by_name = {e.display_name: e for e in result.entries}
        self.assertTrue(by_name["Stylist One"].online_bookable)
        self.assertFalse(by_name["Offline"].online_bookable)
        # Offline member keeps rostered intervals (in-salon booking).
        self.assertEqual(by_name["Offline"].days[0].total_minutes, 480)
        self.assertFalse(by_name["Offline"].days[0].online_bookable)

    def test_inactive_and_other_salon_staff_excluded_ordered_by_name(self):
        StaffMember.objects.create(
            salon=self.salon, display_name="Aardvark", active=False
        )
        StaffMember.objects.create(salon=self.salon, display_name="Zoe")
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        StaffMember.objects.create(salon=other_salon, display_name="Outsider")
        result = roster_week(self.salon, MONDAY)
        self.assertEqual([e.display_name for e in result],
                         ["Stylist One", "Zoe"])
        self.assertEqual(result.staff, result.entries)

    def test_empty_salon_and_no_patterns(self):
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        self.assertEqual(roster_week(empty, MONDAY).entries, [])
        entry = roster_week(self.salon, MONDAY).entries[0]
        self.assertEqual(entry.total_minutes, 0)
        self.assertEqual(entry.working_days, 0)
        self.assertFalse(entry.is_working)

    def test_staff_roster_week_single_member(self):
        self._pattern(weekday=4)
        entry = staff_roster_week(self.staff, MONDAY)
        self.assertEqual(entry.staff_member, self.staff)
        self.assertTrue(entry.days[4].is_working)
        self.assertEqual(entry.by_date[entry.days[4].day], entry.days[4])

    def test_missing_arguments_raise(self):
        with self.assertRaises(ValueError):
            roster_week(None, MONDAY)
        with self.assertRaises(ValueError):
            roster_week(self.salon, None)

    def test_read_only_creates_nothing(self):
        self._pattern()
        before = (StaffMember.objects.count(), RosterPattern.objects.count())
        roster_week(self.salon, MONDAY)
        self.assertEqual(
            (StaffMember.objects.count(), RosterPattern.objects.count()), before
        )
