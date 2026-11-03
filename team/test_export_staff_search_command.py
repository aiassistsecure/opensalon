"""Tests for export_staff_search: stdout/file == service verbatim."""
import io
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon, StaffLevel
from team.models import StaffMember
from team.search_export import export_staff_search_results_csv


class ExportStaffSearchCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.l6 = StaffLevel.objects.create(salon=self.salon, name="Level 6")

    def _staff(self, name, salon=None, **kw):
        return StaffMember.objects.create(
            salon=salon or self.salon, display_name=name,
            staff_level=self.l6 if salon is None else None, **kw)

    def test_stdout_matches_service_output(self):
        self._staff("Amy Smith")
        self._staff("Bob Adams")
        out = io.StringIO()
        call_command("export_staff_search", salon_id=self.salon.id, stdout=out)
        self.assertEqual(out.getvalue(), export_staff_search_results_csv(self.salon))

    def test_query_is_passed_through(self):
        self._staff("Amy Smith")
        self._staff("Bob Adams")
        out = io.StringIO()
        call_command("export_staff_search", salon_id=self.salon.id, query="level 6", stdout=out)
        self.assertEqual(out.getvalue(), export_staff_search_results_csv(self.salon, query="level 6"))
        self.assertIn("Amy", out.getvalue())

    def test_flag_switches_pass_through(self):
        self._staff("Amy Smith", online_bookable=False)
        self._staff("Bob Adams", active=False)
        out = io.StringIO()
        call_command("export_staff_search", salon_id=self.salon.id, not_online_bookable=True, stdout=out)
        self.assertEqual(out.getvalue(), export_staff_search_results_csv(self.salon, online_bookable=False))
        out = io.StringIO()
        call_command("export_staff_search", salon_id=self.salon.id, inactive_only=True, stdout=out)
        self.assertEqual(out.getvalue(), export_staff_search_results_csv(self.salon, active=False))

    def test_output_file_matches_service_output(self):
        self._staff("Amy Smith")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        out = io.StringIO()
        call_command("export_staff_search", salon_id=self.salon.id, query="amy", output=path, stdout=out)
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(data, export_staff_search_results_csv(self.salon, query="amy"))
        self.assertEqual(out.getvalue(), "")

    def test_salon_scoping_and_no_match_header_only(self):
        self._staff("Amy Smith")
        self._staff("Amy Theirs", salon=self.other)
        out = io.StringIO()
        call_command("export_staff_search", salon_id=self.salon.id, query="amy", stdout=out)
        self.assertIn("Smith", out.getvalue()); self.assertNotIn("Theirs", out.getvalue())
        out = io.StringIO()
        call_command("export_staff_search", salon_id=self.salon.id, query="zzz", stdout=out)
        self.assertEqual(out.getvalue(), export_staff_search_results_csv(self.salon, query="zzz"))

    def test_conflicting_flags_raise(self):
        with self.assertRaises(CommandError):
            call_command("export_staff_search", salon_id=self.salon.id, active_only=True, inactive_only=True, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_staff_search", salon_id=self.salon.id, online_bookable_only=True, not_online_bookable=True, stdout=io.StringIO())

    def test_unknown_salon_and_required_id_and_unwritable(self):
        with self.assertRaises(CommandError):
            call_command("export_staff_search", salon_id=999999, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_staff_search", stdout=io.StringIO())
        self._staff("Amy Smith")
        with self.assertRaises(CommandError):
            call_command("export_staff_search", salon_id=self.salon.id, output="/nonexistent-dir/out.csv", stdout=io.StringIO())
