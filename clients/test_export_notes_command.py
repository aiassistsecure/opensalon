"""Tests for the export_notes management command.

Synthetic fixtures only — no real salon/client data. The command is
a thin wrapper around ``clients.note_export.export_notes_csv``;
these tests verify stdout/file output matches that service verbatim
and that salon scoping and invalid input handling apply.
"""
import io
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.models import Client, ClientNote
from clients.note_export import export_notes_csv
from saloncore.models import Salon


class ExportNotesCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")

    def _client_with_note(self, salon, first_name, last_name, body):
        client = Client.objects.create(
            salon=salon, first_name=first_name, last_name=last_name
        )
        ClientNote.objects.create(client=client, body=body)
        return client

    def test_stdout_matches_service_output(self):
        self._client_with_note(self.salon, "Amy", "Smith", "Prefers quiet room")
        self._client_with_note(self.salon, "Bob", "Adams", "Allergic to latex")
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(out.getvalue(), export_notes_csv(self.salon))

    def test_output_file_matches_service_output(self):
        self._client_with_note(self.salon, "Amy", "Smith", "Prefers quiet room")
        self._client_with_note(self.salon, "Bob", "Adams", "Allergic to latex")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id,
            output=path, stdout=out,
        )
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(data, export_notes_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_salon_scoping_excludes_other_salons(self):
        self._client_with_note(self.salon, "Amy", "Smith", "Prefers quiet room")
        self._client_with_note(
            self.other_salon, "Bob", "Adams", "Allergic to latex"
        )
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id, stdout=out
        )
        text = out.getvalue()
        self.assertIn("Amy", text)
        self.assertNotIn("Bob", text)
        self.assertNotIn("Allergic to latex", text)

    def test_empty_book_exports_header_only(self):
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(out.getvalue(), export_notes_csv(self.salon))

    def test_unknown_salon_id_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_notes", salon_id=999999, stdout=io.StringIO()
            )

    def test_salon_id_is_required(self):
        with self.assertRaises(CommandError):
            call_command("export_notes", stdout=io.StringIO())

    def test_unwritable_output_raises(self):
        self._client_with_note(self.salon, "Amy", "Smith", "Prefers quiet room")
        with self.assertRaises(CommandError):
            call_command(
                "export_notes", salon_id=self.salon.id,
                output="/nonexistent-dir/out.csv", stdout=io.StringIO(),
            )
