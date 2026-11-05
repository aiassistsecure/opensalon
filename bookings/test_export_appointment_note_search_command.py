import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from bookings.note_search_export import (
    export_appointment_note_search_results,
    export_appointment_note_search_results_csv,
)
from bookings.test_note_search import SearchAppointmentNotesTests


class ExportAppointmentNoteSearchCommandTests(SearchAppointmentNotesTests):
    def test_stdout_matches_service(self):
        self.make_note(self.appt, "Prefers quiet room")
        self.make_note(self.appt, "Allergic to latex")
        out = io.StringIO()
        call_command("export_appointment_note_search",
                     salon_id=self.salon.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_appointment_note_search_results_csv(self.salon))

    def test_query_passed_through(self):
        self.make_note(self.appt, "Prefers quiet room")
        self.make_note(self.appt, "Allergic to latex")
        out = io.StringIO()
        call_command("export_appointment_note_search", salon_id=self.salon.id,
                     query="quiet", stdout=out)
        self.assertIn("quiet", out.getvalue())
        self.assertNotIn("latex", out.getvalue())

    def test_output_file_matches_service(self):
        self.make_note(self.appt, "Prefers quiet room")
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False, encoding="utf-8") as fh:
            path = fh.name
        call_command("export_appointment_note_search", salon_id=self.salon.id,
                     query="quiet", output=path, stdout=io.StringIO())
        with open(path, encoding="utf-8", newline="") as fh:
            data = fh.read()
        self.assertEqual(data, export_appointment_note_search_results_csv(
            self.salon, query="quiet"))

    def test_salon_scoping(self):
        self.make_note(self.appt, "shared keyword mine")
        self.make_note(self.other_appt, "shared keyword theirs")
        out = io.StringIO()
        call_command("export_appointment_note_search", salon_id=self.salon.id,
                     query="shared keyword", stdout=out)
        self.assertIn("mine", out.getvalue())
        self.assertNotIn("theirs", out.getvalue())

    def test_unknown_salon_raises(self):
        with self.assertRaises(CommandError):
            call_command("export_appointment_note_search", salon_id=999999,
                         stdout=io.StringIO())

    def test_salon_id_required(self):
        with self.assertRaises(CommandError):
            call_command("export_appointment_note_search", stdout=io.StringIO())

    def test_default_and_explicit_csv_match_service(self):
        self.make_note(self.appt, "Prefers quiet room")
        want = export_appointment_note_search_results_csv(self.salon)
        out = io.StringIO()
        call_command("export_appointment_note_search",
                     salon_id=self.salon.id, stdout=out)
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        call_command("export_appointment_note_search",
                     salon_id=self.salon.id, format="csv", stdout=out)
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        call_command("export_appointment_note_search",
                     "--salon-id", str(self.salon.id),
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), want)

    def test_json_output_parses_and_equals_dict_service_rows(self):
        self.make_note(self.appt, "Prefers quiet room")
        self.make_note(self.appt, "Allergic to latex")
        rows = export_appointment_note_search_results(self.salon)
        out = io.StringIO()
        call_command("export_appointment_note_search",
                     salon_id=self.salon.id, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(
            out.getvalue(),
            json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_flag_matches_dict_service(self):
        self.make_note(self.appt, "Prefers quiet room")
        out = io.StringIO()
        call_command("export_appointment_note_search",
                     "--salon-id", str(self.salon.id),
                     "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_appointment_note_search_results(self.salon))

    def test_json_composes_with_query_and_salon(self):
        self.make_note(self.appt, "shared keyword mine")
        self.make_note(self.other_appt, "shared keyword theirs")
        self.make_note(self.appt, "Prefers quiet room")
        rows = export_appointment_note_search_results(
            self.salon, query="shared keyword")
        out = io.StringIO()
        call_command("export_appointment_note_search",
                     salon_id=self.salon.id, query="shared keyword",
                     format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(len(rows), 1)
        self.assertIn("mine", out.getvalue())
        self.assertNotIn("theirs", out.getvalue())
        self.assertNotIn("quiet", out.getvalue())

    def test_json_no_match_is_empty_list(self):
        out = io.StringIO()
        call_command("export_appointment_note_search",
                     salon_id=self.salon.id, query="no-such-text",
                     format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(out.getvalue(), "[]\n")

    def test_json_output_file_matches_dict_service(self):
        self.make_note(self.appt, "Prefers quiet room")
        self.make_note(self.appt, "Allergic to latex")
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "note_search.json")
            call_command("export_appointment_note_search",
                         salon_id=self.salon.id, query="quiet",
                         format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written),
            export_appointment_note_search_results(
                self.salon, query="quiet"))
        self.assertEqual(out.getvalue(), "")

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_appointment_note_search",
                         salon_id=self.salon.id, format="xml",
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_appointment_note_search",
                         "--salon-id", str(self.salon.id),
                         "--format", "xml", stdout=io.StringIO())

    def test_unwritable_output_raises(self):
        self.make_note(self.appt, "Prefers quiet room")
        with self.assertRaises(CommandError):
            call_command("export_appointment_note_search",
                         salon_id=self.salon.id,
                         output="/nonexistent-dir/out.csv",
                         stdout=io.StringIO())
