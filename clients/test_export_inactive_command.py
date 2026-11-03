"""Tests for the export_inactive management command.

Synthetic fixtures only — no real salon/client data. The command is
a thin wrapper around ``clients.inactive_export.export_inactive_csv``;
these tests verify stdout/file output matches that service verbatim
and that salon scoping and invalid input handling apply. Clients
with no appointments are inactive (never visited), so fixtures need
no appointments to appear in the export.
"""
import datetime
import io
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from clients.inactive_export import export_inactive_csv
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
