"""Tests for the export_attendance management command.

The command is a thin wrapper around
``team.attendance_export.export_attendance_summary_csv``:
these tests pin that its stdout and file output match that
service verbatim and that invalid input raises CommandError.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon
from team.attendance_export import export_attendance_summary_csv
from team.models import AttendanceRecord, StaffMember

DAY1 = datetime.date(2026, 11, 2)
DAY2 = datetime.date(2026, 11, 3)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC)


class ExportAttendanceCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        AttendanceRecord.objects.create(
            staff_member=self.staff, event_type="check_in",
            recorded_at=at(DAY1, 9))
        AttendanceRecord.objects.create(
            staff_member=self.staff, event_type="check_out",
            recorded_at=at(DAY1, 17))

    def run_export(self, **kwargs):
        out = io.StringIO()
        call_command("export_attendance", stdout=out, **kwargs)
        return out.getvalue()

    def test_stdout_matches_service(self):
        out = self.run_export(
            salon_id=self.salon.pk, start_date=DAY1, end_date=DAY2)
        self.assertEqual(
            out, export_attendance_summary_csv(self.salon, DAY1, DAY2))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_attendance", "--salon-id", str(self.salon.pk),
            "--start-date", DAY1.isoformat(),
            "--end-date", DAY2.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_attendance_summary_csv(self.salon, DAY1, DAY2))

    def test_output_file_matches_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "attendance.csv")
            out = self.run_export(
                salon_id=self.salon.pk, start_date=DAY1,
                end_date=DAY2, output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    fh.read(),
                    export_attendance_summary_csv(
                        self.salon, DAY1, DAY2))

    def test_unknown_salon_id_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk + 1000,
                start_date=DAY1, end_date=DAY2)

    def test_invalid_date_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk,
                start_date="not-a-date", end_date=DAY2)
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk,
                start_date=DAY1, end_date="2026-13-40")

    def test_reversed_range_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk,
                start_date=DAY2, end_date=DAY1)
