import datetime

from django.test import TestCase

from bookings.models import Break
from bookings.payroll_feed import payroll_feed, payroll_feed_report
from saloncore.models import Salon
from team.models import AttendanceRecord, RosterPattern, ShiftOverride, StaffMember

DAY = datetime.date(2026, 11, 2)  # Monday
NEXT = DAY + datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class PayrollFeedTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=0,
            start_time=datetime.time(9), end_time=datetime.time(17))
        RosterPattern.objects.create(
            staff_member=self.staff2, weekday=0,
            start_time=datetime.time(10), end_time=datetime.time(14))

    def _session(self, staff, day, start, end):
        AttendanceRecord.objects.create(
            staff_member=staff, event_type="check_in", recorded_at=at(day, *start))
        if end is not None:
            AttendanceRecord.objects.create(
                staff_member=staff, event_type="check_out", recorded_at=at(day, *end))

    def _break(self, staff, start, minutes, paid):
        Break.objects.create(
            staff_member=staff, start=start,
            end=start + datetime.timedelta(minutes=minutes), paid=paid)

    def test_combines_roster_attendance_and_breaks(self):
        self._session(self.staff, DAY, (9, 0), (17, 30))
        self._session(self.staff2, DAY, (10, 0), None)
        self._break(self.staff, at(DAY, 12), 30, paid=True)
        self._break(self.staff, at(DAY, 13), 60, paid=False)
        r = payroll_feed(self.salon, DAY, DAY)
        self.assertEqual((r.start_date, r.end_date), (DAY, DAY))
        self.assertEqual([row.staff_name for row in r.by_staff],
                         ["Stylist One", "Stylist Two"])
        one, two = r.by_staff
        self.assertEqual((one.rostered_minutes, one.rostered_days,
                          one.rostered_intervals), (480, 1, 1))
        self.assertEqual((one.actual_minutes, one.attendance_sessions,
                          one.closed_sessions, one.open_sessions), (510, 1, 1, 0))
        self.assertEqual((one.break_count, one.total_break_minutes), (2, 90))
        self.assertEqual((one.paid_break_count, one.paid_minutes), (1, 30))
        self.assertEqual((one.unpaid_break_count, one.unpaid_minutes), (1, 60))
        self.assertEqual((two.rostered_minutes, two.actual_minutes,
                          two.open_sessions), (240, 0, 1))
        self.assertEqual((r.rostered_minutes, r.actual_minutes,
                          r.total_break_minutes), (720, 510, 90))
        self.assertEqual(r.as_dict()["by_staff"][0]["paid_minutes"], 30)

    def test_shift_override_replaces_pattern_and_range_inclusive(self):
        ShiftOverride.objects.create(
            staff_member=self.staff, date=NEXT,
            start_time=datetime.time(9), end_time=datetime.time(12))
        r = payroll_feed_report(self.salon, DAY, NEXT)
        one = r.by_staff[0]
        # Mon pattern 480 + Tue override 180 (no Tue pattern exists).
        self.assertEqual((one.rostered_minutes, one.rostered_days), (660, 2))
        self.assertEqual(payroll_feed(self.salon, NEXT).by_staff[0].rostered_minutes, 180)

    def test_staff_scoping_zero_fill_and_empty(self):
        only = payroll_feed(self.salon, DAY, staff_member=self.staff2)
        self.assertEqual([row.staff_member_id for row in only.by_staff],
                         [self.staff2.pk])
        empty = payroll_feed(self.salon, DAY + datetime.timedelta(days=7))
        self.assertEqual(len(empty.by_staff), 2)
        self.assertTrue(all(row.actual_minutes == 0 and row.break_count == 0
                            for row in empty.by_staff))

    def test_reversed_none_and_salon_isolation(self):
        self.assertEqual(payroll_feed(self.salon, NEXT, DAY).by_staff, ())
        self.assertEqual(payroll_feed(None, DAY).by_staff, ())
        other = Salon.objects.create(name="Other", timezone="UTC")
        outsider = StaffMember.objects.create(salon=other, display_name="Outsider")
        self._break(outsider, at(DAY, 12), 99, paid=True)
        r = payroll_feed(self.salon, DAY)
        self.assertEqual(r.total_break_minutes, 0)
        self.assertNotIn(outsider.pk, [row.staff_member_id for row in r.by_staff])
