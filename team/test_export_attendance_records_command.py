"""Tests for export_attendance_records: stdout/file == service."""
import datetime
import io
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon
from team.attendance_record_export import export_attendance_records_csv
from team.models import AttendanceRecord, StaffMember

UTC = datetime.timezone.utc


class ExportAttendanceRecordsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Record Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Dana")
        AttendanceRecord.objects.create(
            staff_member=self.staff, event_type="check_in",
            recorded_at=datetime.datetime(
                2026, 10, 31, 9, 0, tzinfo=UTC),
            note="front desk")

    def test_stdout_matches_service_output(self):
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_attendance_records_csv(self.salon))
        self.assertIn("Dana", out.getvalue())
        self.assertIn("check_in", out.getvalue())
        self.assertIn("front desk", out.getvalue())

    def test_output_file_matches_service_output(self):
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False,
                encoding="utf-8") as fh:
            path = fh.name
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id, output=path, stdout=out)
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(data, export_attendance_records_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_empty_salon_header_only(self):
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=empty.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_attendance_records_csv(empty))

    def test_unknown_salon_required_id_and_unwritable(self):
        with self.assertRaises(CommandError):
            call_command("export_attendance_records",
                         salon_id=999999, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_attendance_records", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_attendance_records",
                         salon_id=self.salon.id,
                         output="/nonexistent-dir/out.csv",
                         stdout=io.StringIO())
