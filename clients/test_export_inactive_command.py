"""Tests for the export_inactive management command.

Synthetic fixtures only — no real salon/client data. The command is
a thin wrapper around ``clients.inactive_export.export_inactive_csv``
and its dict twin ``export_inactive_clients``;
these tests verify stdout/file output matches that service verbatim
and that salon scoping and invalid input handling apply. Clients
with no appointments are inactive (never visited), so fixtures need
no appointments to appear in the export.
"""
import csv
import datetime
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from bookings.models import Appointment
from clients.inactive_export import (
    export_inactive_clients,
    export_inactive_csv,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


class ExportInactiveCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")

    def _client(self, salon, first_name, last_name, **kwargs):
        return Client.objects.create(
            salon=salon, first_name=first_name, last_name=last_name, **kwargs
        )

    def _visited_client(self, first_name, last_name, days_ago):
        client = self._client(self.salon, first_name, last_name)
        staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        start = NOW - datetime.timedelta(days=days_ago)
        Appointment.objects.create(
            client=client, staff_member=staff, service=service,
            start=start, end=start + datetime.timedelta(minutes=45))
        return client

    def test_stdout_matches_service_output(self):
        self._client(self.salon, "Amy", "Smith")
        self._client(self.salon, "Bob", "Adams")
        out = io.StringIO()
        call_command(
            "export_inactive", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(out.getvalue(), export_inactive_csv(self.salon))

    def test_output_file_matches_service_output(self):
        self._client(self.salon, "Amy", "Smith")
        self._client(self.salon, "Bob", "Adams")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        out = io.StringIO()
        call_command(
            "export_inactive", salon_id=self.salon.id,
            output=path, stdout=out,
        )
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(data, export_inactive_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_salon_scoping_excludes_other_salons(self):
        self._client(self.salon, "Amy", "Smith")
        self._client(self.other_salon, "Bob", "Adams")
        out = io.StringIO()
        call_command(
            "export_inactive", salon_id=self.salon.id, stdout=out
        )
        text = out.getvalue()
        self.assertIn("Amy", text)
        self.assertNotIn("Bob", text)

    def test_empty_book_exports_header_only(self):
        out = io.StringIO()
        call_command(
            "export_inactive", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(out.getvalue(), export_inactive_csv(self.salon))

    def test_unknown_salon_id_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_inactive", salon_id=999999, stdout=io.StringIO()
            )

    def test_salon_id_is_required(self):
        with self.assertRaises(CommandError):
            call_command("export_inactive", stdout=io.StringIO())

    def test_days_changes_exported_rows(self):
        # Visit 30 days before NOW: active under the 90-day
        # default, inactive under a 14-day window.
        self._visited_client("Tessa", "Threshold", 30)
        out = io.StringIO()
        call_command(
            "export_inactive", salon_id=self.salon.id, now=NOW,
            stdout=out)
        self.assertNotIn("Tessa", out.getvalue())
        self.assertEqual(
            out.getvalue(), export_inactive_csv(self.salon, now=NOW))
        out = io.StringIO()
        call_command(
            "export_inactive", salon_id=self.salon.id, days=14,
            now=NOW, stdout=out)
        self.assertIn("Tessa", out.getvalue())
        self.assertEqual(
            out.getvalue(),
            export_inactive_csv(self.salon, days=14, now=NOW))

    def test_threshold_days_changes_exported_rows(self):
        self._visited_client("Tessa", "Threshold", 30)
        out = io.StringIO()
        call_command(
            "export_inactive", salon_id=self.salon.id,
            threshold_days=14, now=NOW, stdout=out)
        self.assertIn("Tessa", out.getvalue())
        self.assertEqual(
            out.getvalue(),
            export_inactive_csv(
                self.salon, threshold_days=14, now=NOW))

    def test_now_changes_exported_rows(self):
        # Visit 30 days before NOW is recent at NOW but stale
        # 100 days later; --now as an ISO string works too.
        self._visited_client("Tessa", "Threshold", 30)
        later = NOW + datetime.timedelta(days=100)
        out = io.StringIO()
        call_command(
            "export_inactive", salon_id=self.salon.id,
            now=later.isoformat(), stdout=out)
        self.assertIn("Tessa", out.getvalue())
        self.assertEqual(
            out.getvalue(),
            export_inactive_csv(self.salon, now=later))

    def test_invalid_now_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_inactive", salon_id=self.salon.id,
                now="not-a-datetime", stdout=io.StringIO())

    def test_unwritable_output_raises(self):
        self._client(self.salon, "Amy", "Smith")
        with self.assertRaises(CommandError):
            call_command(
                "export_inactive", salon_id=self.salon.id,
                output="/nonexistent-dir/out.csv", stdout=io.StringIO(),
            )

    def test_default_and_explicit_csv_byte_identical(self):
        self._client(self.salon, "Amy", "Smith")
        self._client(self.salon, "Bob", "Adams")
        expected = export_inactive_csv(self.salon)
        for kwargs in ({}, {"format": "csv"}):
            out = io.StringIO()
            call_command(
                "export_inactive", salon_id=self.salon.id,
                stdout=out, **kwargs)
            self.assertEqual(out.getvalue(), expected)

    def test_json_stdout_equals_dict_rows(self):
        self._visited_client("Tessa", "Threshold", 120)
        self._client(self.salon, "Amy", "Smith")
        out = io.StringIO()
        call_command(
            "export_inactive", salon_id=self.salon.id, now=NOW,
            format="json", stdout=out)
        rows = export_inactive_clients(self.salon, now=NOW)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(
            out.getvalue(),
            json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_and_csv_rows_agree(self):
        self._visited_client("Tessa", "Threshold", 120)
        self._client(self.salon, "Amy", "Smith")
        csv_out = io.StringIO()
        call_command(
            "export_inactive", salon_id=self.salon.id, now=NOW,
            format="csv", stdout=csv_out)
        json_out = io.StringIO()
        call_command(
            "export_inactive", salon_id=self.salon.id, now=NOW,
            format="json", stdout=json_out)
        csv_rows = list(csv.DictReader(io.StringIO(csv_out.getvalue())))
        json_rows = json.loads(json_out.getvalue())
        self.assertEqual(len(csv_rows), len(json_rows))
        for csv_row, json_row in zip(csv_rows, json_rows):
            self.assertEqual(list(csv_row), list(json_row))
            for key, value in json_row.items():
                self.assertEqual(
                    csv_row[key], "" if value is None else str(value))

    def test_json_via_cli_flags(self):
        self._client(self.salon, "Amy", "Smith")
        out = io.StringIO()
        call_command(
            "export_inactive", "--salon-id", str(self.salon.id),
            "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_inactive_clients(self.salon))

    def test_json_output_file(self):
        self._client(self.salon, "Amy", "Smith")
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "inactive.json")
            call_command(
                "export_inactive", salon_id=self.salon.id,
                format="json", output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written), export_inactive_clients(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_json_composes_with_days_and_now(self):
        self._visited_client("Tessa", "Threshold", 30)
        out = io.StringIO()
        call_command(
            "export_inactive", salon_id=self.salon.id, days=14,
            now=NOW, format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_inactive_clients(self.salon, days=14, now=NOW))
        self.assertIn("Tessa", out.getvalue())

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_inactive", salon_id=self.salon.id,
                format="xml", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_inactive", "--salon-id", str(self.salon.id),
                "--format", "xml", stdout=io.StringIO())
