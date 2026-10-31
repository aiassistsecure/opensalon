"""Tests for the export_optin_summary management command.

Synthetic fixtures only — no real salon/client data. The command is
a thin wrapper around ``clients.optin_export.export_optin_summary``;
these tests verify stdout/file output matches that service verbatim
and that salon scoping and invalid input handling apply.
"""
import io
import json
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.models import Client
from clients.optin_export import export_optin_summary
from saloncore.models import Salon


class ExportOptinSummaryCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")

    def _client(self, salon, first_name, last_name, **kwargs):
        return Client.objects.create(
            salon=salon, first_name=first_name, last_name=last_name, **kwargs
        )

    def test_stdout_matches_service_output(self):
        self._client(
            self.salon, "Amy", "Smith", sms_opt_in=True, email_opt_in=True
        )
        self._client(self.salon, "Bob", "Adams", sms_opt_in=True)
        self._client(self.salon, "Cid", "Jones", email_opt_in=True)
        self._client(self.salon, "Dee", "Brown")
        out = io.StringIO()
        call_command(
            "export_optin_summary", salon_id=self.salon.id, stdout=out
        )
        expected = export_optin_summary(self.salon)
        self.assertEqual(json.loads(out.getvalue()), expected)
        self.assertEqual(expected, {
            "total": 4, "sms_opt_in": 2, "email_opt_in": 2,
            "both_opt_in": 1, "sms_only": 1, "email_only": 1,
            "neither_opt_in": 1,
        })

    def test_output_file_matches_service_output(self):
        self._client(self.salon, "Amy", "Smith", email_opt_in=True)
        self._client(self.salon, "Bob", "Adams")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        out = io.StringIO()
        call_command(
            "export_optin_summary", salon_id=self.salon.id,
            output=path, stdout=out,
        )
        with open(path, encoding="utf-8") as exported:
            data = json.load(exported)
        self.assertEqual(data, export_optin_summary(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_salon_scoping_excludes_other_salons(self):
        self._client(self.salon, "Amy", "Smith", sms_opt_in=True)
        self._client(
            self.other_salon, "Bob", "Adams",
            sms_opt_in=True, email_opt_in=True,
        )
        out = io.StringIO()
        call_command(
            "export_optin_summary", salon_id=self.salon.id, stdout=out
        )
        data = json.loads(out.getvalue())
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["sms_opt_in"], 1)
        self.assertEqual(data["both_opt_in"], 0)

    def test_empty_book_exports_zero_counts(self):
        out = io.StringIO()
        call_command(
            "export_optin_summary", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(json.loads(out.getvalue()), {
            "total": 0, "sms_opt_in": 0, "email_opt_in": 0,
            "both_opt_in": 0, "sms_only": 0, "email_only": 0,
            "neither_opt_in": 0,
        })

    def test_unknown_salon_id_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_optin_summary", salon_id=999999,
                stdout=io.StringIO(),
            )

    def test_salon_id_is_required(self):
        with self.assertRaises(CommandError):
            call_command("export_optin_summary", stdout=io.StringIO())

    def test_unwritable_output_raises(self):
        self._client(self.salon, "Amy", "Smith")
        with self.assertRaises(CommandError):
            call_command(
                "export_optin_summary", salon_id=self.salon.id,
                output="/nonexistent-dir/out.json", stdout=io.StringIO(),
            )
