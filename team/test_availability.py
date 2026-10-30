import datetime

from django.test import TestCase
from django.utils import timezone

from saloncore.models import Salon
from team.availability import (
    check_in,
    check_out,
    roster_availability,
    rostered_intervals,
    salon_roster,
)
from team.models import AttendanceRecord, RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday
TUESDAY = datetime.date(2026, 11, 3)
UTC = datetime.timezone.utc


def at(day, hour, minute=0, tz=UTC):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=tz)


class RosterAvailabilityTests(TestCase):
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

    def _pairs(self, result):
        return [(i.start, i.end) for i in result.intervals]

    def test_single_pattern_returns_aware_interval(self):
        self._pattern()
        result = roster_availability(self.staff, MONDAY)
        self.assertEqual(self._pairs(result), [(at(MONDAY, 9), at(MONDAY, 17))])
        self.assertTrue(result.is_working)
        self.assertEqual(result.total_minutes, 480)
        self.assertEqual(result.day, MONDAY)
        self.assertEqual(result.staff_member, self.staff)

    def test_no_pattern_that_weekday_is_not_working(self):
        self._pattern(weekday=0)
        result = roster_availability(self.staff, TUESDAY)
        self.assertEqual(result.intervals, ())
        self.assertFalse(result.is_working)
        self.assertEqual(result.total_minutes, 0)

    def test_split_shift_stays_two_intervals(self):
        self._pattern(end=(12, 0))
        self._pattern(start=(13, 0))
        self.assertEqual(
            self._pairs(roster_availability(self.staff, MONDAY)),
            [(at(MONDAY, 9), at(MONDAY, 12)), (at(MONDAY, 13), at(MONDAY, 17))],
        )

    def test_overlapping_and_touching_patterns_merge(self):
        self._pattern(end=(13, 0))
        self._pattern(start=(12, 0))
        self._pattern(start=(17, 0), end=(19, 0))
        self.assertEqual(
            self._pairs(roster_availability(self.staff, MONDAY)),
            [(at(MONDAY, 9), at(MONDAY, 19))],
        )

    def test_inactive_pattern_and_other_staff_excluded(self):
        other = StaffMember.objects.create(salon=self.salon, display_name="Two")
        self._pattern()
        self._pattern(start=(18, 0), end=(19, 0), active=False)
        self._pattern(staff=other, start=(18, 0), end=(20, 0))
        result = roster_availability(self.staff, MONDAY)
        self.assertEqual(self._pairs(result), [(at(MONDAY, 9), at(MONDAY, 17))])

    def test_inactive_staff_has_no_intervals(self):
        inactive = StaffMember.objects.create(
            salon=self.salon, display_name="Gone", active=False
        )
        self._pattern(staff=inactive)
        self.assertEqual(roster_availability(inactive, MONDAY).intervals, ())

    def test_online_bookable_is_separate_flag_not_a_filter(self):
        offline = StaffMember.objects.create(
            salon=self.salon, display_name="Offline", online_bookable=False
        )
        self._pattern(); self._pattern(staff=offline)
        offline_result = roster_availability(offline, MONDAY)
        # Rostered time survives the toggle — in-salon booking can use it.
        self.assertEqual(
            self._pairs(offline_result), [(at(MONDAY, 9), at(MONDAY, 17))]
        )
        self.assertFalse(offline_result.online_bookable)
        self.assertTrue(roster_availability(self.staff, MONDAY).online_bookable)

    def test_salon_timezone_applies_to_intervals(self):
        salon = Salon.objects.create(
            name="NY Salon", timezone="America/New_York"
        )
        member = StaffMember.objects.create(salon=salon, display_name="NY One")
        self._pattern(staff=member)
        result = roster_availability(member, MONDAY)
        start = result.intervals[0].start
        self.assertEqual((start.hour, start.utcoffset()),
                         (9, datetime.timedelta(hours=-5)))  # EST in Nov

    def test_datetime_input_reduced_in_salon_timezone(self):
        self._pattern()
        # 01:30 UTC on Tuesday is still Monday evening in New York,
        # but this salon is UTC: Tuesday input yields Tuesday (no roster).
        late = at(TUESDAY, 1, 30)
        self.assertEqual(roster_availability(self.staff, late).day, TUESDAY)
        self.assertEqual(
            rostered_intervals(self.staff, at(MONDAY, 23, 0)),
            roster_availability(self.staff, MONDAY).intervals,
        )

    def test_rostered_intervals_shortcut(self):
        self._pattern()
        intervals = rostered_intervals(self.staff, MONDAY)
        self.assertEqual(len(intervals), 1)
        self.assertEqual(intervals[0].minutes, 480)

    def test_salon_roster_includes_off_members_excludes_inactive(self):
        off = StaffMember.objects.create(salon=self.salon, display_name="Off Day")
        StaffMember.objects.create(
            salon=self.salon, display_name="Inactive", active=False
        )
        self._pattern()
        results = salon_roster(self.salon, MONDAY)
        by_name = {r.staff_member.display_name: r for r in results}
        self.assertEqual(sorted(by_name), ["Off Day", "Stylist One"])
        self.assertTrue(by_name["Stylist One"].is_working)
        self.assertFalse(by_name["Off Day"].is_working)


class CheckInOutServiceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.t0 = timezone.now() - datetime.timedelta(hours=4)

    def test_check_in_records_event_and_state(self):
        rec = check_in(self.staff, recorded_at=self.t0, note="On time")
        self.assertEqual(rec.event_type, AttendanceRecord.EventType.CHECK_IN)
        self.assertEqual(rec.staff_member, self.staff)
        self.assertEqual(rec.recorded_at, self.t0)
        self.assertEqual(rec.note, "On time")
        self.assertTrue(self.staff.is_checked_in())

    def test_check_in_defaults_to_now(self):
        before = timezone.now()
        rec = check_in(self.staff)
        self.assertGreaterEqual(rec.recorded_at, before)
        self.assertEqual(rec.note, "")

    def test_duplicate_check_in_raises_and_records_nothing(self):
        check_in(self.staff, recorded_at=self.t0)
        with self.assertRaises(ValueError):
            check_in(self.staff)
        self.assertEqual(AttendanceRecord.objects.count(), 1)

    def test_check_out_after_check_in(self):
        check_in(self.staff, recorded_at=self.t0)
        rec = check_out(
            self.staff, recorded_at=self.t0 + datetime.timedelta(hours=8)
        )
        self.assertEqual(rec.event_type, AttendanceRecord.EventType.CHECK_OUT)
        self.assertFalse(self.staff.is_checked_in())

    def test_check_out_without_check_in_raises_and_records_nothing(self):
        with self.assertRaises(ValueError):
            check_out(self.staff)
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_full_cycle_allows_second_check_in(self):
        check_in(self.staff, recorded_at=self.t0)
        check_out(self.staff, recorded_at=self.t0 + datetime.timedelta(hours=4))
        check_in(self.staff, recorded_at=self.t0 + datetime.timedelta(hours=5))
        self.assertTrue(self.staff.is_checked_in())
        self.assertEqual(AttendanceRecord.objects.count(), 3)
