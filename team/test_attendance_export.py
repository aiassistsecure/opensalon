import csv
import datetime
import io

from django.test import TestCase

from saloncore.models import Salon
from team.attendance_export import (
    ATTENDANCE_EXPORT_FIELDNAMES,
    attendance_summary_csv,
    export_attendance_summary,
    export_attendance_summary_csv,
)
from team.attendance_summary import attendance_summary
from team.models import AttendanceRecord, StaffMember

DAY1 = datetime.date(2026, 11, 2)  # Monday
DAY2 = datetime.date(2026, 11, 3)
DAY3 = datetime.date(2026, 11, 4)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC)


class AttendanceExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.other = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")

    def _session(self, staff, day, start=(9, 0), end=(17, 0)):
        AttendanceRecord.objects.create(
            staff_member=staff, event_type="check_in",
            recorded_at=at(day, *start))
        if end is not None:
            AttendanceRecord.objects.create(
                staff_member=staff, event_type="check_out",
                recorded_at=at(day, *end))

    def _fixture(self):
        self._session(self.staff, DAY1)  # closed, 480 min
        self._session(self.staff, DAY3, start=(9, 0), end=None)  # open
        self._session(self.other, DAY1, start=(10, 0), end=(14, 0))

    def test_header_and_dict_keys(self):
        self._fixture()
        text = export_attendance_summary_csv(self.salon, DAY1, DAY3)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], ATTENDANCE_EXPORT_FIELDNAMES)
        records = export_attendance_summary(self.salon, DAY1, DAY3)
        self.assertTrue(records)
        for record in records:
            self.assertEqual(
                list(record.keys()), ATTENDANCE_EXPORT_FIELDNAMES)
        # Short alias is the same function.
        self.assertIs(attendance_summary_csv, export_attendance_summary_csv)
        self.assertEqual(
            attendance_summary_csv(self.salon, DAY1, DAY3), text)

    def test_rows_match_service_output_on_same_fixture(self):
        self._fixture()
        summary = attendance_summary(self.salon, DAY1, DAY3)
        records = export_attendance_summary(self.salon, DAY1, DAY3)
        staff_rows = [r for r in records if r["section"] == "staff"]
        self.assertEqual(
            [(r["staff_member_id"], r["staff_name"], r["sessions_count"],
              r["closed_sessions"], r["open_sessions"], r["total_minutes"])
             for r in staff_rows],
            [(e.staff_member_id, e.display_name, e.sessions_count,
              e.closed_sessions, e.open_sessions, e.total_minutes)
             for e in summary.per_staff])
        day_rows = [r for r in records if r["section"] == "day"]
        self.assertEqual(
            [(r["date"], r["sessions_count"], r["closed_sessions"],
              r["open_sessions"], r["total_minutes"], r["staff_count"])
             for r in day_rows],
            [(e.day.isoformat(), e.sessions_count, e.closed_sessions,
              e.open_sessions, e.total_minutes, e.staff_count)
             for e in summary.per_day])
        self.assertTrue(all(
            r["salon_id"] == summary.salon_id
            and r["start_date"] == summary.start_date.isoformat()
            and r["end_date"] == summary.end_date.isoformat()
            for r in records))
        self.assertEqual(
            sum(r["sessions_count"] for r in staff_rows),
            summary.sessions_count)
        # CSV agrees with the dict export on the same arguments.
        parsed = list(csv.DictReader(io.StringIO(
            export_attendance_summary_csv(self.salon, DAY1, DAY3))))
        self.assertEqual(len(parsed), len(records))
        self.assertEqual(
            [(r["section"], r["sessions_count"], r["total_minutes"])
             for r in parsed],
            [(r["section"], str(r["sessions_count"]),
              str(r["total_minutes"])) for r in records])

    def test_empty_range_carries_service_zero_filled_rows(self):
        summary = attendance_summary(self.salon, DAY1, DAY2)
        records = export_attendance_summary(self.salon, DAY1, DAY2)
        self.assertEqual(len(records),
                         len(summary.per_staff) + len(summary.per_day))
        self.assertTrue(records)
        self.assertTrue(all(
            r["sessions_count"] == 0 and r["total_minutes"] == 0
            for r in records))
        self.assertEqual(
            [r["date"] for r in records if r["section"] == "day"],
            [DAY1.isoformat(), DAY2.isoformat()])

    def test_service_arguments_passed_through_unchanged(self):
        self._fixture()
        # Keyword range aliases the service itself accepts.
        by_kwarg = export_attendance_summary_csv(
            self.salon, start_date=DAY1, end_date=DAY1)
        by_alias = export_attendance_summary_csv(
            self.salon, date_from=DAY1, date_to=DAY1)
        expected = export_attendance_summary_csv(self.salon, DAY1, DAY1)
        self.assertEqual(by_kwarg, expected)
        self.assertEqual(by_alias, expected)
        # Datetime bounds are reduced by the service, not here.
        by_datetime = export_attendance_summary_csv(
            self.salon, at(DAY1, 12), at(DAY1, 13))
        self.assertEqual(by_datetime, expected)
        # Range-only call (no salon): only staff with sessions,
        # and no salon id on any row.
        records = export_attendance_summary(DAY1, DAY1)
        self.assertTrue(all(r["salon_id"] is None for r in records))
        self.assertEqual(
            [r["staff_name"] for r in records if r["section"] == "staff"],
            [e.display_name for e in attendance_summary(DAY1, DAY1).per_staff])

    def test_read_only(self):
        self._fixture()
        before_records = AttendanceRecord.objects.count()
        before_staff = StaffMember.objects.count()
        export_attendance_summary(self.salon, DAY1, DAY3)
        export_attendance_summary_csv(self.salon, DAY1, DAY3)
        self.assertEqual(AttendanceRecord.objects.count(), before_records)
        self.assertEqual(StaffMember.objects.count(), before_staff)
