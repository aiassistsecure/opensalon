"""Tests for the export_client management command.

Synthetic fixtures only — no real salon/client data. The command
is a thin wrapper around ``clients.export.export_client``; these
tests verify stdout/file output matches that service verbatim
and that salon scoping and invalid input handling apply. The
command name ``export_client`` is not shared with any other app,
so plain ``call_command`` resolves to this clients command.
"""
import io
import json
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.export import export_client
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
