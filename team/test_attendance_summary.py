import datetime

from django.test import TestCase

from saloncore.models import Salon
from team.attendance_summary import attendance_summary
from team.models import AttendanceRecord, StaffMember

DAY1 = datetime.date(2026, 11, 2)  # Monday
DAY2 = datetime.date(2026, 11, 3)
DAY3 = datetime.date(2026, 11, 4)
UTC = datetime.timezone.utc


def at(day, hour, minute=0, tz=UTC):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=tz)


class AttendanceSummaryTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.other = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two"
        )

    def _event(self, staff, kind, when):
        return AttendanceRecord.objects.create(
            staff_member=staff, event_type=kind, recorded_at=when
        )

    def _session(self, staff, day, start=(9, 0), end=(17, 0)):
        self._event(staff, "check_in", at(day, *start))
        if end is not None:
            self._event(staff, "check_out", at(day, *end))

    def test_closed_session_counts_and_duration_per_staff(self):
        self._session(self.staff, DAY1)
        result = attendance_summary(self.salon, DAY1, DAY1)
        entry = result.for_staff(self.staff)
        self.assertEqual(entry.sessions_count, 1)
        self.assertEqual(entry.session_count, 1)
        self.assertEqual(entry.closed_sessions, 1)
        self.assertEqual(entry.open_sessions, 0)
        self.assertEqual(entry.total_duration, datetime.timedelta(hours=8))
        self.assertEqual(entry.total_minutes, 480)
        self.assertEqual(result.total_sessions, 1)
        self.assertEqual(result.total_minutes, 480)
        self.assertEqual(result.start_date, DAY1)
        self.assertEqual(result.end_date, DAY1)

    def test_open_session_counted_separately_with_no_duration(self):
        self._session(self.staff, DAY1, end=None)
        result = attendance_summary(self.salon, DAY1, DAY1)
        entry = result.for_staff(self.staff)
        self.assertEqual(entry.sessions_count, 1)
        self.assertEqual(entry.open_sessions, 1)
        self.assertEqual(entry.closed_sessions, 0)
        self.assertEqual(entry.total_duration, datetime.timedelta(0))
        self.assertEqual(result.open_sessions, 1)

    def test_multiple_sessions_sum_and_split_staff(self):
        self._session(self.staff, DAY1, end=(12, 0))
        self._session(self.staff, DAY1, start=(13, 0), end=(17, 0))
        self._session(self.other, DAY1, start=(10, 0), end=(14, 0))
        result = attendance_summary(self.salon, DAY1, DAY1)
        self.assertEqual(result.for_staff(self.staff).total_minutes, 420)
        self.assertEqual(result.for_staff(self.staff).sessions_count, 2)
        self.assertEqual(result.for_staff(self.other).total_minutes, 240)
        self.assertEqual([e.display_name for e in result.per_staff],
                         ["Stylist One", "Stylist Two"])
        self.assertEqual(result.by_staff[self.staff.pk].total_minutes, 420)

    def test_per_day_totals_zero_filled_and_inclusive_range(self):
        self._session(self.staff, DAY1)
        self._session(self.other, DAY3, start=(9, 0), end=(13, 0))
        result = attendance_summary(self.salon, DAY1, DAY3)
        self.assertEqual([d.day for d in result.per_day], [DAY1, DAY2, DAY3])
        self.assertEqual(result.by_day[DAY1].sessions_count, 1)
        self.assertEqual(result.by_day[DAY1].total_minutes, 480)
        self.assertEqual(result.by_day[DAY1].staff_count, 1)
        self.assertEqual(result.by_day[DAY2].sessions_count, 0)
        self.assertEqual(result.by_day[DAY2].total_duration,
                         datetime.timedelta(0))
        self.assertEqual(result.by_day[DAY3].total_minutes, 240)
        self.assertEqual(result.for_day(DAY3).closed_sessions, 1)

    def test_sessions_outside_range_excluded(self):
        self._session(self.staff, DAY1)
        self._session(self.staff, DAY3)
        result = attendance_summary(self.salon, DAY2, DAY2)
        self.assertEqual(result.total_sessions, 0)
        self.assertEqual(result.for_staff(self.staff).sessions_count, 0)

    def test_session_attributed_to_check_in_day_across_midnight(self):
        self._event(self.staff, "check_in", at(DAY1, 22))
        self._event(self.staff, "check_out", at(DAY2, 2))
        result = attendance_summary(self.salon, DAY1, DAY1)
        self.assertEqual(result.total_sessions, 1)
        self.assertEqual(result.total_minutes, 240)
        self.assertEqual(result.by_day[DAY1].total_minutes, 240)

    def test_local_date_uses_salon_timezone(self):
        salon = Salon.objects.create(
            name="NY", timezone="America/New_York"
        )
        member = StaffMember.objects.create(salon=salon, display_name="NY")
        # 02:00-06:00 UTC on DAY2 is 21:00-01:00 EST starting DAY1.
        self._event(member, "check_in", at(DAY2, 2))
        self._event(member, "check_out", at(DAY2, 6))
        result = attendance_summary(salon, DAY1, DAY1)
        self.assertEqual(result.total_sessions, 1)
        self.assertEqual(result.total_minutes, 240)

    def test_other_salon_and_orphan_checkout_ignored(self):
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        outsider = StaffMember.objects.create(
            salon=other_salon, display_name="Outsider"
        )
        self._session(outsider, DAY1)
        self._event(self.staff, "check_out", at(DAY1, 17))
        result = attendance_summary(self.salon, DAY1, DAY1)
        self.assertEqual(result.total_sessions, 0)
        self.assertIsNone(result.for_staff(outsider))

    def test_zero_filled_active_staff_and_empty_range(self):
        result = attendance_summary(self.salon, DAY1, DAY2)
        self.assertEqual(len(result.per_staff), 2)
        self.assertTrue(all(e.sessions_count == 0 for e in result))
        self.assertEqual(result.total_duration, datetime.timedelta(0))
        self.assertEqual(len(result.per_day), 2)

    def test_reversed_range_and_missing_dates_raise(self):
        with self.assertRaises(ValueError):
            attendance_summary(self.salon, DAY3, DAY1)
        with self.assertRaises(ValueError):
            attendance_summary(self.salon, DAY1, None)

    def test_datetime_range_reduced_and_read_only(self):
        self._session(self.staff, DAY1)
        before = AttendanceRecord.objects.count()
        result = attendance_summary(self.salon, at(DAY1, 12), at(DAY1, 13))
        self.assertEqual(result.start_date, DAY1)
        self.assertEqual(AttendanceRecord.objects.count(), before)
        self.assertEqual(StaffMember.objects.count(), 2)

    def test_range_only_call_lists_only_staff_with_sessions(self):
        self._session(self.staff, DAY1)
        result = attendance_summary(DAY1, DAY1)
        self.assertEqual([e.display_name for e in result.per_staff],
                         ["Stylist One"])
