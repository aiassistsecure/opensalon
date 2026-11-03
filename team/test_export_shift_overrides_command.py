"""Tests for export_shift_overrides: stdout/file == service."""
import datetime
import io
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon
from team.models import ShiftOverride, StaffMember
from team.shift_override_export import export_shift_overrides_csv


class ExportShiftOverridesCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Override Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Dana")
        ShiftOverride.objects.create(
            staff_member=self.staff, date=datetime.date(2026, 10, 31),
            start_time=datetime.time(10, 0),
            end_time=datetime.time(14, 0))

    def test_stdout_matches_service_output(self):
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=self.salon.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_shift_overrides_csv(self.salon))
        self.assertIn("Dana", out.getvalue())
        self.assertIn("2026-10-31", out.getvalue())

    def test_output_file_matches_service_output(self):
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False,
                encoding="utf-8") as fh:
            path = fh.name
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=self.salon.id, output=path, stdout=out)
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(data, export_shift_overrides_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_empty_salon_header_only(self):
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=empty.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_shift_overrides_csv(empty))

    def test_unknown_salon_required_id_and_unwritable(self):
        with self.assertRaises(CommandError):
            call_command("export_shift_overrides",
                         salon_id=999999, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_shift_overrides", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_shift_overrides",
                         salon_id=self.salon.id,
                         output="/nonexistent-dir/out.csv",
                         stdout=io.StringIO())
