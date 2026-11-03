"""Tests for export_capability_matrix: stdout/file == service."""
import io
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon, Service, ServiceCategory
from team.capability_export import export_capability_matrix_csv
from team.models import StaffMember, StaffService


class ExportCapabilityMatrixCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Matrix Salon", timezone="UTC")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        service = Service.objects.create(
            category=category, name="Cut", service_minutes=60)
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Dana")
        StaffService.objects.create(
            staff_member=self.staff, service=service, enabled=True)

    def test_stdout_matches_service_output(self):
        out = io.StringIO()
        call_command("export_capability_matrix",
                     salon_id=self.salon.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_capability_matrix_csv(self.salon))
        self.assertIn("Dana", out.getvalue())
        self.assertIn("Cut", out.getvalue())

    def test_output_file_matches_service_output(self):
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False,
                encoding="utf-8") as fh:
            path = fh.name
        out = io.StringIO()
        call_command("export_capability_matrix",
                     salon_id=self.salon.id, output=path, stdout=out)
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(data, export_capability_matrix_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_empty_salon_header_only(self):
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        out = io.StringIO()
        call_command("export_capability_matrix",
                     salon_id=empty.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_capability_matrix_csv(empty))

    def test_unknown_salon_required_id_and_unwritable(self):
        with self.assertRaises(CommandError):
            call_command("export_capability_matrix",
                         salon_id=999999, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_capability_matrix", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_capability_matrix",
                         salon_id=self.salon.id,
                         output="/nonexistent-dir/out.csv",
                         stdout=io.StringIO())
