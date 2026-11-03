"""Tests for the export_client management command.

Synthetic fixtures only — no real salon/client data. The command
is a thin wrapper around ``clients.export.export_client``; these
tests verify stdout/file output matches that service verbatim
and that salon scoping and invalid input handling apply. The
command name ``export_client`` is not shared with any other app,
so plain ``call_command`` resolves to this clients command.
"""
import csv
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.export import (
    CLIENT_FIELDNAMES,
    export_client,
    export_client_csv,
)
from clients.models import Client, ClientNote
from saloncore.models import Salon


class ExportClientCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")
        self.client = Client.objects.create(
            salon=self.salon, external_id="ext-42",
            first_name="Amy", last_name="Smith",
            email="amy@example.com", phone="555-0101",
            sms_opt_in=True, email_opt_in=False,
        )

    def _call(self, **kwargs):
        out = io.StringIO()
        call_command("export_client", stdout=out, **kwargs)
        return out

    def test_stdout_matches_service_output(self):
        ClientNote.objects.create(
            client=self.client, body="Record note",
            author_name="Front Desk",
        )
        out = self._call(salon_id=self.salon.id, client_id=self.client.id)
        expected = export_client(self.client)
        self.assertEqual(json.loads(out.getvalue()), expected)
        self.assertEqual(out.getvalue(), json.dumps(expected, indent=2) + "\n")
        self.assertEqual(expected["first_name"], "Amy")
        self.assertEqual(expected["notes"][0]["body"], "Record note")

    def test_output_file_matches_service_output(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        out = io.StringIO()
        call_command(
            "export_client", salon_id=self.salon.id,
            client_id=self.client.id, output=path, stdout=out,
        )
        with open(path, encoding="utf-8") as exported:
            data = json.load(exported)
        self.assertEqual(data, export_client(self.client))
        self.assertEqual(out.getvalue(), "")

    def test_client_with_no_notes_exports_empty_list(self):
        out = self._call(salon_id=self.salon.id, client_id=self.client.id)
        self.assertEqual(json.loads(out.getvalue())["notes"], [])

    def test_other_salon_client_is_not_exported(self):
        other = Client.objects.create(
            salon=self.other_salon, first_name="Bob", last_name="Adams"
        )
        with self.assertRaises(CommandError):
            self._call(salon_id=self.salon.id, client_id=other.id)

    def test_unknown_salon_id_raises(self):
        with self.assertRaises(CommandError):
            self._call(salon_id=999999, client_id=self.client.id)

    def test_unknown_client_id_raises(self):
        with self.assertRaises(CommandError):
            self._call(salon_id=self.salon.id, client_id=999999)

    def test_salon_id_is_required(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_client", client_id=self.client.id,
                stdout=io.StringIO(),
            )

    def test_client_id_is_required(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_client", salon_id=self.salon.id,
                stdout=io.StringIO(),
            )

    def test_unwritable_output_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_client", salon_id=self.salon.id,
                client_id=self.client.id,
                output="/nonexistent-dir/out.json", stdout=io.StringIO(),
            )

    def test_default_format_remains_json(self):
        out = self._call(salon_id=self.salon.id, client_id=self.client.id)
        expected = export_client(self.client)
        self.assertEqual(
            out.getvalue(), json.dumps(expected, indent=2) + "\n")

    def test_explicit_json_format_matches_service(self):
        out = self._call(
            salon_id=self.salon.id, client_id=self.client.id,
            format="json",
        )
        expected = export_client(self.client)
        self.assertEqual(
            out.getvalue(), json.dumps(expected, indent=2) + "\n")

    def test_csv_format_matches_service(self):
        ClientNote.objects.create(
            client=self.client, body="Record note",
            author_name="Front Desk",
        )
        out = self._call(
            salon_id=self.salon.id, client_id=self.client.id,
            format="csv",
        )
        self.assertEqual(out.getvalue(), export_client_csv(self.client))

    def test_csv_flag_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_client", "--salon-id", str(self.salon.id),
            "--client-id", str(self.client.id),
            "--format", "csv", stdout=out,
        )
        self.assertEqual(out.getvalue(), export_client_csv(self.client))

    def test_csv_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "client.csv")
            call_command(
                "export_client", salon_id=self.salon.id,
                client_id=self.client.id, format="csv",
                output=path, stdout=out,
            )
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, export_client_csv(self.client))
        self.assertEqual(out.getvalue(), "")

    def test_csv_header_and_field_order(self):
        out = self._call(
            salon_id=self.salon.id, client_id=self.client.id,
            format="csv",
        )
        text = out.getvalue()
        self.assertEqual(
            text.splitlines()[0], ",".join(CLIENT_FIELDNAMES))
        reader = csv.DictReader(io.StringIO(text))
        self.assertEqual(reader.fieldnames, CLIENT_FIELDNAMES)

    def test_csv_content_equals_json_record(self):
        self.client.payload = {"source_ref": "abc-1"}
        self.client.save()
        ClientNote.objects.create(
            client=self.client, body="Record note",
            author_name="Front Desk",
        )
        out = self._call(
            salon_id=self.salon.id, client_id=self.client.id,
            format="csv",
        )
        expected = export_client(self.client)
        parsed = list(csv.DictReader(io.StringIO(out.getvalue())))
        self.assertEqual(len(parsed), 1)
        row = parsed[0]
        for field in (
            "id", "salon_id", "external_id", "first_name",
            "last_name", "email", "phone", "sms_opt_in",
            "email_opt_in", "active", "created_at",
        ):
            self.assertEqual(row[field], str(expected[field]))
        self.assertEqual(json.loads(row["notes"]), expected["notes"])
        self.assertEqual(json.loads(row["payload"]), expected["payload"])

    def test_csv_no_notes_and_no_payload_cells(self):
        out = self._call(
            salon_id=self.salon.id, client_id=self.client.id,
            format="csv",
        )
        parsed = list(csv.DictReader(io.StringIO(out.getvalue())))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(json.loads(parsed[0]["notes"]), [])
        self.assertEqual(parsed[0]["payload"], "")

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(
                salon_id=self.salon.id, client_id=self.client.id,
                format="xml",
            )
