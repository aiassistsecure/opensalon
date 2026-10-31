"""Tests for the export_client_search management command.

Synthetic fixtures only -- no real salon/client data. The command
is a thin wrapper around
``clients.search_export.export_search_results_csv``; these tests
verify stdout/file output matches that service verbatim and that
salon scoping, query passthrough, and invalid input handling apply.
"""
import io
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.models import Client
from clients.search_export import export_search_results_csv
from saloncore.models import Salon


class ExportClientSearchCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")
        Client.objects.create(
            salon=self.salon, first_name="Amy", last_name="Smith",
            email="amy.smith@example.com", phone="555-0101")
        Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Adams",
            email="bob@sample.org", phone="555-0199")
        Client.objects.create(
            salon=self.other_salon, first_name="Amy", last_name="Smith",
            email="amy.smith@example.com", phone="555-0101")

    def test_stdout_matches_service_output(self):
        out = io.StringIO()
        call_command(
            "export_client_search", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(
            out.getvalue(), export_search_results_csv(self.salon))

    def test_query_is_passed_through(self):
        out = io.StringIO()
        call_command(
            "export_client_search", salon_id=self.salon.id,
            query="smith", stdout=out,
        )
        self.assertEqual(
            out.getvalue(),
            export_search_results_csv(self.salon, query="smith"))
        self.assertIn("Amy", out.getvalue())
        self.assertNotIn("Bob", out.getvalue())

    def test_output_file_matches_service_output(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        out = io.StringIO()
        call_command(
            "export_client_search", salon_id=self.salon.id,
            query="smith", output=path, stdout=out,
        )
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(
            data, export_search_results_csv(self.salon, query="smith"))
        self.assertEqual(out.getvalue(), "")

    def test_salon_scoping_excludes_other_salons(self):
        out = io.StringIO()
        call_command(
            "export_client_search", salon_id=self.salon.id,
            query="amy", stdout=out,
        )
        text = out.getvalue()
        self.assertEqual(text.count("Amy"), 1)

    def test_no_match_exports_header_only(self):
        out = io.StringIO()
        call_command(
            "export_client_search", salon_id=self.salon.id,
            query="no-such-text", stdout=out,
        )
        self.assertEqual(
            out.getvalue(),
            export_search_results_csv(self.salon, query="no-such-text"))

    def test_unknown_salon_id_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_client_search", salon_id=999999,
                stdout=io.StringIO(),
            )

    def test_salon_id_is_required(self):
        with self.assertRaises(CommandError):
            call_command("export_client_search", stdout=io.StringIO())

    def test_unwritable_output_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_client_search", salon_id=self.salon.id,
                output="/nonexistent-dir/out.csv", stdout=io.StringIO(),
            )
