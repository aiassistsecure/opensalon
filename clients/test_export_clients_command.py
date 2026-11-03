"""Tests for the export_clients management command.

Synthetic fixtures only — no real salon/client data. The command is
a thin wrapper around ``clients.export_all.export_all_clients``;
these tests verify stdout/file output matches that service verbatim
and that salon scoping applies.
"""
import csv
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.export_all import (
    CLIENTS_FIELDNAMES,
    export_all_clients,
    export_all_clients_csv,
)
from clients.models import Client, ClientNote
from saloncore.models import Salon


class ExportClientsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")

    def _client(self, salon, first_name, last_name, **kwargs):
        return Client.objects.create(
            salon=salon, first_name=first_name, last_name=last_name, **kwargs
        )

    def test_stdout_matches_service_output(self):
        amy = self._client(
            self.salon, "Amy", "Smith", email="amy@example.com",
            sms_opt_in=True,
        )
        self._client(self.salon, "Bob", "Adams")
        ClientNote.objects.create(client=amy, body="A note")
        out = io.StringIO()
        call_command(
            "export_clients", salon_id=self.salon.id, stdout=out
        )
        expected = export_all_clients(salon=self.salon)
        self.assertEqual(json.loads(out.getvalue()), expected)
        self.assertEqual(len(expected), 2)
        self.assertEqual(expected[1]["note_count"], 1)

    def test_output_file_matches_service_output(self):
        self._client(self.salon, "Amy", "Smith")
        self._client(self.salon, "Bob", "Adams")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        out = io.StringIO()
        call_command(
            "export_clients", salon_id=self.salon.id,
            output=path, stdout=out,
        )
        with open(path, encoding="utf-8") as exported:
            data = json.load(exported)
        self.assertEqual(data, export_all_clients(salon=self.salon))
        self.assertEqual(len(data), 2)

    def test_salon_scoping_excludes_other_salons(self):
        self._client(self.salon, "Amy", "Smith")
        self._client(self.other_salon, "Bob", "Adams")
        out = io.StringIO()
        call_command(
            "export_clients", salon_id=self.salon.id, stdout=out
        )
        data = json.loads(out.getvalue())
        self.assertEqual([c["first_name"] for c in data], ["Amy"])
        out = io.StringIO()
        call_command(
            "export_clients", salon_id=self.other_salon.id, stdout=out
        )
        data = json.loads(out.getvalue())
        self.assertEqual([c["first_name"] for c in data], ["Bob"])

    def test_empty_book_exports_empty_list(self):
        out = io.StringIO()
        call_command(
            "export_clients", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(json.loads(out.getvalue()), [])

    def test_unknown_salon_id_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_clients", salon_id=999999, stdout=io.StringIO()
            )

    def test_salon_id_is_required(self):
        with self.assertRaises(CommandError):
            call_command("export_clients", stdout=io.StringIO())

    def test_default_format_remains_json(self):
        self._client(self.salon, "Amy", "Smith")
        self._client(self.salon, "Bob", "Adams")
        out = io.StringIO()
        call_command(
            "export_clients", salon_id=self.salon.id, stdout=out
        )
        expected = export_all_clients(salon=self.salon)
        self.assertEqual(
            out.getvalue(), json.dumps(expected, indent=2) + "\n")

    def test_explicit_json_format_matches_service(self):
        self._client(self.salon, "Amy", "Smith")
        out = io.StringIO()
        call_command(
            "export_clients", salon_id=self.salon.id,
            format="json", stdout=out,
        )
        expected = export_all_clients(salon=self.salon)
        self.assertEqual(
            out.getvalue(), json.dumps(expected, indent=2) + "\n")

    def test_csv_format_matches_service(self):
        self._client(self.salon, "Amy", "Smith")
        self._client(self.salon, "Bob", "Adams")
        out = io.StringIO()
        call_command(
            "export_clients", salon_id=self.salon.id,
            format="csv", stdout=out,
        )
        self.assertEqual(
            out.getvalue(), export_all_clients_csv(salon=self.salon))

    def test_csv_flag_matches_service(self):
        self._client(self.salon, "Amy", "Smith")
        out = io.StringIO()
        call_command(
            "export_clients", "--salon-id", str(self.salon.id),
            "--format", "csv", stdout=out,
        )
        self.assertEqual(
            out.getvalue(), export_all_clients_csv(salon=self.salon))

    def test_csv_output_file_matches_service(self):
        self._client(self.salon, "Amy", "Smith")
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "clients.csv")
            call_command(
                "export_clients", salon_id=self.salon.id,
                format="csv", output=path, stdout=out,
            )
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(
            text, export_all_clients_csv(salon=self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_csv_header_and_field_order(self):
        self._client(self.salon, "Amy", "Smith")
        out = io.StringIO()
        call_command(
            "export_clients", salon_id=self.salon.id,
            format="csv", stdout=out,
        )
        text = out.getvalue()
        self.assertEqual(
            text.splitlines()[0], ",".join(CLIENTS_FIELDNAMES))
        reader = csv.DictReader(io.StringIO(text))
        self.assertEqual(reader.fieldnames, CLIENTS_FIELDNAMES)

    def test_csv_content_equals_json_rows(self):
        amy = self._client(
            self.salon, "Amy", "Smith", email="amy@example.com",
            sms_opt_in=True, payload={"source_ref": "abc-1"},
        )
        self._client(self.salon, "Bob", "Adams")
        ClientNote.objects.create(client=amy, body="A note")
        out = io.StringIO()
        call_command(
            "export_clients", salon_id=self.salon.id,
            format="csv", stdout=out,
        )
        expected = export_all_clients(salon=self.salon)
        parsed = list(csv.DictReader(io.StringIO(out.getvalue())))
        self.assertEqual(len(parsed), len(expected))
        for row, record in zip(parsed, expected):
            for field in (
                "id", "salon_id", "external_id", "first_name",
                "last_name", "email", "phone", "sms_opt_in",
                "email_opt_in", "active", "created_at", "note_count",
            ):
                self.assertEqual(row[field], str(record[field]))
            self.assertEqual(json.loads(row["notes"]), record["notes"])
            if "payload" in record:
                self.assertEqual(
                    json.loads(row["payload"]), record["payload"])
            else:
                self.assertEqual(row["payload"], "")

    def test_empty_book_csv_is_header_only(self):
        out = io.StringIO()
        call_command(
            "export_clients", salon_id=self.salon.id,
            format="csv", stdout=out,
        )
        self.assertEqual(
            out.getvalue(), ",".join(CLIENTS_FIELDNAMES) + "\n")

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_clients", salon_id=self.salon.id,
                format="xml", stdout=io.StringIO(),
            )
