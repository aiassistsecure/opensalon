"""Tests for the export_note_search management command.

Synthetic fixtures only -- no real salon/client data. The command
is a thin wrapper around
``clients.note_search_export.export_note_search_results_csv``;
these tests verify stdout/file output matches that service verbatim
and that salon scoping, query passthrough, and invalid input
handling apply.
"""
import io
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.models import Client, ClientNote
from clients.note_search_export import export_note_search_results_csv
from saloncore.models import Salon


class ExportNoteSearchCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")

    def _note(self, salon, first_name, last_name, body):
        client = Client.objects.create(
            salon=salon, first_name=first_name, last_name=last_name)
        return ClientNote.objects.create(client=client, body=body)

    def test_stdout_matches_service_output(self):
        self._note(self.salon, "Amy", "Smith", "Prefers quiet room")
        self._note(self.salon, "Bob", "Adams", "Allergic to latex")
        out = io.StringIO()
        call_command("export_note_search", salon_id=self.salon.id, stdout=out)
        self.assertEqual(
            out.getvalue(), export_note_search_results_csv(self.salon))

    def test_query_is_passed_through(self):
        self._note(self.salon, "Amy", "Smith", "Prefers quiet room")
        self._note(self.salon, "Bob", "Adams", "Allergic to latex")
        out = io.StringIO()
        call_command(
            "export_note_search", salon_id=self.salon.id,
            query="quiet", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_note_search_results_csv(self.salon, query="quiet"))
        self.assertIn("Amy", out.getvalue())
        self.assertNotIn("Bob", out.getvalue())

    def test_output_file_matches_service_output(self):
        self._note(self.salon, "Amy", "Smith", "Prefers quiet room")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        out = io.StringIO()
        call_command(
            "export_note_search", salon_id=self.salon.id,
            query="quiet", output=path, stdout=out)
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(
            data,
            export_note_search_results_csv(self.salon, query="quiet"))
        self.assertEqual(out.getvalue(), "")

    def test_salon_scoping_excludes_other_salons(self):
        self._note(self.salon, "Amy", "Smith", "shared keyword mine")
        self._note(self.other_salon, "Bob", "Adams", "shared keyword theirs")
        out = io.StringIO()
        call_command(
            "export_note_search", salon_id=self.salon.id,
            query="shared keyword", stdout=out)
        text = out.getvalue()
        self.assertIn("mine", text)
        self.assertNotIn("theirs", text)

    def test_no_match_exports_header_only(self):
        self._note(self.salon, "Amy", "Smith", "Prefers quiet room")
        out = io.StringIO()
        call_command(
            "export_note_search", salon_id=self.salon.id,
            query="no-such-text", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_note_search_results_csv(
                self.salon, query="no-such-text"))

    def test_unknown_salon_id_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_note_search", salon_id=999999,
                stdout=io.StringIO())

    def test_salon_id_is_required(self):
        with self.assertRaises(CommandError):
            call_command("export_note_search", stdout=io.StringIO())

    def test_unwritable_output_raises(self):
        self._note(self.salon, "Amy", "Smith", "Prefers quiet room")
        with self.assertRaises(CommandError):
            call_command(
                "export_note_search", salon_id=self.salon.id,
                output="/nonexistent-dir/out.csv", stdout=io.StringIO())
