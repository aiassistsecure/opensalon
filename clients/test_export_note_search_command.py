"""Tests for the export_note_search management command.

Synthetic fixtures only -- no real salon/client data. The command
is a thin wrapper around
``clients.note_search_export.export_note_search_results_csv``;
these tests verify stdout/file output matches that service verbatim
and that salon scoping, query passthrough, and invalid input
handling apply.
"""
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from clients.models import Client, ClientNote
from clients.note_search_export import (
    export_note_search_results,
    export_note_search_results_csv,
)
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

    def test_default_and_explicit_csv_match_service(self):
        self._note(self.salon, "Amy", "Smith", "Prefers quiet room")
        want = export_note_search_results_csv(self.salon)
        out = io.StringIO()
        call_command("export_note_search", salon_id=self.salon.id, stdout=out)
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        call_command(
            "export_note_search", salon_id=self.salon.id,
            format="csv", stdout=out)
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        call_command(
            "export_note_search", "--salon-id", str(self.salon.id),
            "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), want)

    def test_json_output_parses_and_equals_dict_service_rows(self):
        self._note(self.salon, "Amy", "Smith", "Prefers quiet room")
        self._note(self.salon, "Bob", "Adams", "Allergic to latex")
        rows = export_note_search_results(self.salon)
        out = io.StringIO()
        call_command(
            "export_note_search", salon_id=self.salon.id,
            format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(
            out.getvalue(),
            json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_flag_matches_dict_service(self):
        self._note(self.salon, "Amy", "Smith", "Prefers quiet room")
        out = io.StringIO()
        call_command(
            "export_note_search", "--salon-id", str(self.salon.id),
            "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_note_search_results(self.salon))

    def test_json_composes_with_query_and_salon(self):
        self._note(self.salon, "Amy", "Smith", "shared keyword mine")
        self._note(self.other_salon, "Bob", "Adams", "shared keyword theirs")
        self._note(self.salon, "Amy", "Smith", "Prefers quiet room")
        rows = export_note_search_results(
            self.salon, query="shared keyword")
        out = io.StringIO()
        call_command(
            "export_note_search", salon_id=self.salon.id,
            query="shared keyword", format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(len(rows), 1)
        self.assertIn("mine", out.getvalue())
        self.assertNotIn("theirs", out.getvalue())
        self.assertNotIn("quiet", out.getvalue())

    def test_json_no_match_is_empty_list(self):
        self._note(self.salon, "Amy", "Smith", "Prefers quiet room")
        out = io.StringIO()
        call_command(
            "export_note_search", salon_id=self.salon.id,
            query="no-such-text", format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(out.getvalue(), "[]\n")

    def test_json_output_file_matches_dict_service(self):
        self._note(self.salon, "Amy", "Smith", "Prefers quiet room")
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "note_search.json")
            call_command(
                "export_note_search", salon_id=self.salon.id,
                query="quiet", format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written),
            export_note_search_results(self.salon, query="quiet"))
        self.assertEqual(out.getvalue(), "")

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_note_search", salon_id=self.salon.id,
                format="xml", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_note_search", "--salon-id", str(self.salon.id),
                "--format", "xml", stdout=io.StringIO())

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
