"""Tests for export_staff_search: stdout/file == service verbatim."""
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from saloncore.models import Salon, StaffLevel
from team.models import StaffMember
from team.search_export import (
    export_staff_search_results,
    export_staff_search_results_csv,
)


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

    def test_default_and_explicit_csv_match_service(self):
        self._staff("Amy Smith")
        self._staff("Bob Adams")
        want = export_staff_search_results_csv(self.salon)
        out = io.StringIO()
        call_command("export_staff_search", salon_id=self.salon.id, stdout=out)
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        call_command("export_staff_search", salon_id=self.salon.id, format="csv", stdout=out)
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        call_command("export_staff_search", "--salon-id", str(self.salon.id), "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), want)

    def test_json_output_parses_and_equals_dict_service_rows(self):
        self._staff("Amy Smith")
        self._staff("Bob Adams")
        rows = export_staff_search_results(self.salon)
        out = io.StringIO()
        call_command("export_staff_search", salon_id=self.salon.id, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(
            out.getvalue(),
            json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")
        self.assertIsInstance(json.loads(out.getvalue())[0]["id"], int)

    def test_json_flag_matches_dict_service(self):
        self._staff("Amy Smith")
        out = io.StringIO()
        call_command("export_staff_search", "--salon-id", str(self.salon.id), "--format", "json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), export_staff_search_results(self.salon))

    def test_json_composes_with_filters(self):
        self._staff("Amy Smith", online_bookable=False)
        self._staff("Bob Adams", active=False)
        self._staff("Cara Jones")
        cases = [
            ({"query": "amy"}, {"query": "amy"}),
            ({"inactive_only": True}, {"active": False}),
            ({"active_only": True}, {"active": True}),
            ({"not_online_bookable": True}, {"online_bookable": False}),
            ({"online_bookable_only": True}, {"online_bookable": True}),
            ({"query": "level 6", "active_only": True},
             {"query": "level 6", "active": True}),
        ]
        for cmd_kw, svc_kw in cases:
            out = io.StringIO()
            call_command("export_staff_search", salon_id=self.salon.id, format="json", stdout=out, **cmd_kw)
            self.assertEqual(
                json.loads(out.getvalue()),
                export_staff_search_results(self.salon, **svc_kw))

    def test_json_salon_scoping_and_no_match(self):
        self._staff("Amy Smith")
        self._staff("Amy Theirs", salon=self.other)
        out = io.StringIO()
        call_command("export_staff_search", salon_id=self.salon.id, query="amy", format="json", stdout=out)
        names = [r["display_name"] for r in json.loads(out.getvalue())]
        self.assertEqual(names, ["Amy Smith"])
        out = io.StringIO()
        call_command("export_staff_search", salon_id=self.salon.id, query="zzz", format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])

    def test_json_output_file_matches_dict_service(self):
        self._staff("Amy Smith")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "staff_search.json")
            out = io.StringIO()
            call_command("export_staff_search", salon_id=self.salon.id, query="amy", format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(json.loads(written), export_staff_search_results(self.salon, query="amy"))
        self.assertEqual(out.getvalue(), "")

    def test_invalid_format_raises_command_error(self):
        self._staff("Amy Smith")
        with self.assertRaises(CommandError):
            call_command("export_staff_search", salon_id=self.salon.id, format="xml", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_staff_search", "--salon-id", str(self.salon.id), "--format", "xml", stdout=io.StringIO())

    def test_unknown_salon_and_required_id_and_unwritable(self):
        with self.assertRaises(CommandError):
            call_command("export_staff_search", salon_id=999999, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_staff_search", stdout=io.StringIO())
        self._staff("Amy Smith")
        with self.assertRaises(CommandError):
            call_command("export_staff_search", salon_id=self.salon.id, output="/nonexistent-dir/out.csv", stdout=io.StringIO())
