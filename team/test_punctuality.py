"""Tests for the team punctuality report service and CSV export."""
import csv
import datetime
import io
from decimal import Decimal

from django.test import TestCase

from saloncore.models import Salon
from team.models import AttendanceRecord, RosterPattern, ShiftOverride, StaffMember
from team.punctuality import punctuality_report
from team.punctuality_export import (
    PUNCTUALITY_EXPORT_FIELDNAMES, export_punctuality,
    export_punctuality_csv, punctuality_csv)

MON = datetime.date(2026, 11, 2)  # Monday
TUE = datetime.date(2026, 11, 3)
WED = datetime.date(2026, 11, 4)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class PunctualityTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.other = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.unrostered = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Three")
        # staff + other rostered Mon-Wed 09:00-17:00; Three never.
        for member in (self.staff, self.other):
            for weekday in (0, 1, 2):
                RosterPattern.objects.create(
                    staff_member=member, weekday=weekday,
                    start_time=datetime.time(9, 0),
                    end_time=datetime.time(17, 0))

    def _check_in(self, staff, day, start=(9, 0)):
        return AttendanceRecord.objects.create(
            staff_member=staff, event_type="check_in",
            recorded_at=at(day, *start))

    def test_on_time_and_early_count_as_on_time(self):
        self._check_in(self.staff, MON, (9, 0))   # exactly at start
        self._check_in(self.staff, TUE, (8, 45))  # early
        self._check_in(self.staff, WED, (9, 0))
        entry = punctuality_report(self.salon, MON, WED).for_staff(self.staff)
        self.assertEqual((entry.shifts_considered, entry.on_time_count,
                          entry.late_count, entry.missed_count), (3, 3, 0, 0))
        self.assertEqual(entry.total_late_minutes, 0)
        self.assertEqual(entry.average_late_minutes, Decimal("0.00"))

    def test_late_counts_total_and_average(self):
        self._check_in(self.staff, MON, (9, 10))
        self._check_in(self.staff, TUE, (9, 20))
        self._check_in(self.staff, WED, (9, 0))
        result = punctuality_report(self.salon, MON, WED)
        entry = result.for_staff(self.staff)
        self.assertEqual((entry.late_count, entry.on_time_count), (2, 1))
        self.assertEqual(entry.total_late_minutes, 30)
        self.assertEqual(entry.average_late_minutes, Decimal("15.00"))
        self.assertEqual(result.total_late_minutes, 30)
        self.assertEqual(result.late_count, 2)

    def test_missed_shift_is_considered_but_neither_on_time_nor_late(self):
        self._check_in(self.staff, MON)
        entry = punctuality_report(self.salon, MON, WED).for_staff(self.staff)
        self.assertEqual((entry.shifts_considered, entry.on_time_count,
                          entry.late_count, entry.missed_count), (3, 1, 0, 2))

    def test_staff_with_no_rostered_shifts_excluded(self):
        self._check_in(self.unrostered, MON, (12, 0))
        result = punctuality_report(self.salon, MON, WED)
        self.assertIsNone(result.for_staff(self.unrostered))
        self.assertEqual([e.display_name for e in result.per_staff],
                         ["Stylist One", "Stylist Two"])

    def test_earliest_check_in_of_day_wins(self):
        self._check_in(self.staff, MON, (9, 30))
        self._check_in(self.staff, MON, (8, 50))
        entry = punctuality_report(self.salon, MON, MON).for_staff(self.staff)
        self.assertEqual((entry.on_time_count, entry.late_count), (1, 0))

    def test_split_shift_counts_once_from_first_interval(self):
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=3,
            start_time=datetime.time(9, 0), end_time=datetime.time(12, 0))
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=3,
            start_time=datetime.time(13, 0), end_time=datetime.time(17, 0))
        thu = datetime.date(2026, 11, 5)  # Thursday, weekday 3
        self._check_in(self.staff, thu, (9, 5))
        entry = punctuality_report(self.salon, thu, thu).for_staff(self.staff)
        self.assertEqual((entry.shifts_considered, entry.late_count,
                          entry.total_late_minutes), (1, 1, 5))

    def test_override_moves_start_and_off_day_drops_shift(self):
        ShiftOverride.objects.create(
            staff_member=self.staff, date=MON,
            start_time=datetime.time(10, 0), end_time=datetime.time(18, 0))
        ShiftOverride.objects.create(
            staff_member=self.staff, date=TUE, is_off=True)
        self._check_in(self.staff, MON, (9, 30))  # early vs 10:00 override
        self._check_in(self.staff, WED, (9, 0))
        entry = punctuality_report(self.salon, MON, WED).for_staff(self.staff)
        self.assertEqual((entry.shifts_considered, entry.on_time_count,
                          entry.missed_count), (2, 2, 0))

    def test_check_out_and_other_salon_check_ins_ignored(self):
        AttendanceRecord.objects.create(
            staff_member=self.staff, event_type="check_out",
            recorded_at=at(MON, 8, 0))
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        outsider = StaffMember.objects.create(
            salon=other_salon, display_name="Outsider")
        self._check_in(outsider, MON, (8, 0))
        entry = punctuality_report(self.salon, MON, MON).for_staff(self.staff)
        self.assertEqual((entry.on_time_count, entry.missed_count), (0, 1))

    def test_salon_timezone_start_and_check_in(self):
        salon = Salon.objects.create(name="NY", timezone="America/New_York")
        member = StaffMember.objects.create(salon=salon, display_name="NY")
        RosterPattern.objects.create(
            staff_member=member, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0))
        # 14:15 UTC Mon = 09:15 EST Mon: 15 minutes late.
        self._check_in(member, MON, (14, 15))
        entry = punctuality_report(salon, MON, MON).for_staff(member)
        self.assertEqual((entry.late_count, entry.total_late_minutes), (1, 15))

    def test_reversed_and_missing_raise(self):
        with self.assertRaises(ValueError):
            punctuality_report(self.salon, WED, MON)
        with self.assertRaises(ValueError):
            punctuality_report(self.salon, MON, None)
        with self.assertRaises(ValueError):
            punctuality_report(None, MON, WED)

    def test_read_only(self):
        self._check_in(self.staff, MON, (9, 10))
        before = AttendanceRecord.objects.count()
        punctuality_report(self.salon, MON, WED)
        export_punctuality_csv(self.salon, MON, WED)
        self.assertEqual(AttendanceRecord.objects.count(), before)

    def test_export_dict_and_csv_match_service(self):
        self._check_in(self.staff, MON, (9, 10))
        self._check_in(self.staff, TUE, (9, 20))
        self._check_in(self.other, MON, (9, 0))
        rows = export_punctuality(self.salon, MON, WED)
        self.assertEqual(list(rows[0].keys()), PUNCTUALITY_EXPORT_FIELDNAMES)
        # Unrostered staff excluded from export too.
        self.assertEqual([r["staff_name"] for r in rows],
                         ["Stylist One", "Stylist Two"])
        row = rows[0]
        self.assertEqual((row["shifts_considered"], row["late_count"],
                          row["missed_count"], row["total_late_minutes"],
                          row["average_late_minutes"]),
                         (3, 2, 1, 30, "15.00"))
        parsed = list(csv.DictReader(io.StringIO(
            export_punctuality_csv(self.salon, MON, WED))))
        self.assertEqual(len(parsed), len(rows))
        self.assertEqual(parsed[0]["total_late_minutes"], "30")
        self.assertEqual(parsed[0]["average_late_minutes"], "15.00")
        self.assertIs(punctuality_csv, export_punctuality_csv)
