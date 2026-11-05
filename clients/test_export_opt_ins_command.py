"""Tests for the export_opt_ins management command.

Synthetic fixtures only — no real salon/client data. The command is
a thin wrapper around ``clients.optin_export.export_optins_csv``;
these tests verify stdout/file output matches that service verbatim
and that salon scoping and invalid input handling apply.
"""
import io
import json
import tempfile
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.models import Client
from clients.optin_export import export_optins, export_optins_csv
from saloncore.models import Salon


class ExportOptInsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")

    def _client(self, salon, first_name, last_name, **kwargs):
        return Client.objects.create(
            salon=salon, first_name=first_name, last_name=last_name, **kwargs
        )

    def test_stdout_matches_service_output(self):
        self._client(
            self.salon, "Amy", "Smith", email="amy@example.com",
            sms_opt_in=True, email_opt_in=True,
        )
        self._client(self.salon, "Bob", "Adams", sms_opt_in=True)
        out = io.StringIO()
        call_command(
            "export_opt_ins", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(out.getvalue(), export_optins_csv(self.salon))

    def test_output_file_matches_service_output(self):
        self._client(self.salon, "Amy", "Smith", email_opt_in=True)
        self._client(self.salon, "Bob", "Adams")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        out = io.StringIO()
        call_command(
            "export_opt_ins", salon_id=self.salon.id,
            output=path, stdout=out,
        )
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(data, export_optins_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_salon_scoping_excludes_other_salons(self):
        self._client(self.salon, "Amy", "Smith", sms_opt_in=True)
        self._client(self.other_salon, "Bob", "Adams", sms_opt_in=True)
        out = io.StringIO()
        call_command(
            "export_opt_ins", salon_id=self.salon.id, stdout=out
        )
        text = out.getvalue()
        self.assertIn("Amy", text)
        self.assertNotIn("Bob", text)

    def test_empty_book_exports_header_only(self):
        out = io.StringIO()
        call_command(
            "export_opt_ins", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(out.getvalue(), export_optins_csv(self.salon))

    def test_unknown_salon_id_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_opt_ins", salon_id=999999, stdout=io.StringIO()
            )

    def test_salon_id_is_required(self):
        with self.assertRaises(CommandError):
            call_command("export_opt_ins", stdout=io.StringIO())

    def test_unwritable_output_raises(self):
        self._client(self.salon, "Amy", "Smith")
        with self.assertRaises(CommandError):
            call_command(
                "export_opt_ins", salon_id=self.salon.id,
                output="/nonexistent-dir/out.csv", stdout=io.StringIO(),
            )

    def test_default_format_is_csv_byte_identical(self):
        self._client(
            self.salon, "Amy", "Smith", email="amy@example.com",
            sms_opt_in=True, email_opt_in=True,
        )
        out = io.StringIO()
        call_command(
            "export_opt_ins", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(out.getvalue(), export_optins_csv(self.salon))

    def test_explicit_csv_format_matches_service(self):
        self._client(self.salon, "Amy", "Smith", sms_opt_in=True)
        out = io.StringIO()
        call_command(
            "export_opt_ins", salon_id=self.salon.id,
            format="csv", stdout=out,
        )
        self.assertEqual(out.getvalue(), export_optins_csv(self.salon))

    def test_json_output_parses_and_equals_dict_service_rows(self):
        self._client(
            self.salon, "Amy", "Smith", email="amy@example.com",
            sms_opt_in=True, email_opt_in=True,
        )
        self._client(self.salon, "Bob", "Adams", sms_opt_in=True)
        out = io.StringIO()
        call_command(
            "export_opt_ins", salon_id=self.salon.id,
            format="json", stdout=out,
        )
        self.assertEqual(
            json.loads(out.getvalue()), export_optins(self.salon))

    def test_json_flag_matches_dict_service(self):
        self._client(self.salon, "Amy", "Smith", sms_opt_in=True)
        out = io.StringIO()
        call_command(
            "export_opt_ins", "--salon-id", str(self.salon.id),
            "--format", "json", stdout=out,
        )
        self.assertEqual(
            json.loads(out.getvalue()), export_optins(self.salon))
        self.assertIn("Amy", out.getvalue())

    def test_json_empty_book_exports_empty_list(self):
        out = io.StringIO()
        call_command(
            "export_opt_ins", salon_id=self.salon.id,
            format="json", stdout=out,
        )
        self.assertEqual(json.loads(out.getvalue()), [])

    def test_json_output_file_matches_dict_service(self):
        self._client(self.salon, "Amy", "Smith", email_opt_in=True)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        out = io.StringIO()
        call_command(
            "export_opt_ins", salon_id=self.salon.id,
            format="json", output=path, stdout=out,
        )
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(json.loads(data), export_optins(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_json_salon_scoping_excludes_other_salons(self):
        self._client(self.salon, "Amy", "Smith", sms_opt_in=True)
        self._client(self.other_salon, "Bob", "Adams", sms_opt_in=True)
        out = io.StringIO()
        call_command(
            "export_opt_ins", salon_id=self.salon.id,
            format="json", stdout=out,
        )
        self.assertEqual(
            json.loads(out.getvalue()), export_optins(self.salon))
        self.assertIn("Amy", out.getvalue())
        self.assertNotIn("Bob", out.getvalue())

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_opt_ins", salon_id=self.salon.id,
                format="xml", stdout=io.StringIO(),
            )

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command(
                "export_opt_ins", "--salon-id", str(self.salon.id),
                "--format", "xml", stdout=io.StringIO(),
            )

    def test_json_service_error_surfaces_as_command_error(self):
        with mock.patch(
            "clients.management.commands.export_opt_ins.export_optins",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "export_opt_ins", salon_id=self.salon.id,
                    format="json", stdout=io.StringIO(),
                )
