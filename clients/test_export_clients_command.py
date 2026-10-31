"""Tests for the export_clients management command.

Synthetic fixtures only — no real salon/client data. The command is
a thin wrapper around ``clients.export_all.export_all_clients``;
these tests verify stdout/file output matches that service verbatim
and that salon scoping applies.
"""
import io
import json
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.export_all import export_all_clients
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
