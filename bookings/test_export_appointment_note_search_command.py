import io
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.note_search_export import (
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

    def test_unwritable_output_raises(self):
        self.make_note(self.appt, "Prefers quiet room")
        with self.assertRaises(CommandError):
            call_command("export_appointment_note_search",
                         salon_id=self.salon.id,
                         output="/nonexistent-dir/out.csv",
                         stdout=io.StringIO())
