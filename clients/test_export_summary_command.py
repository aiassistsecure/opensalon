"""Tests for the export_summary (clients) management command.

Synthetic fixtures only -- no real salon/client data. The command
is a thin wrapper around
``clients.summary_export.export_client_summaries_csv``; these
tests verify stdout/file output matches that service verbatim and
that salon scoping and invalid input handling apply.

These tests load the clients command class explicitly via
``load_command_class("clients", "export_summary")`` and pass that
instance to ``call_command`` -- pinning this app's command, not
the global name resolution (checkout owns the same global name).
"""
import datetime
import io
import tempfile

from django.core.management import CommandError, call_command, load_command_class
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from clients.summary_export import export_client_summaries_csv
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def _cmd():
    return load_command_class("clients", "export_summary")


def at(day_offset, hour=9):
    return NOW + datetime.timedelta(days=day_offset, hours=hour - 12)


class ExportSummaryCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(
            name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)

    def _client(self, first, last, salon=None, with_visit=False):
        client = Client.objects.create(
            salon=salon or self.salon, first_name=first, last_name=last)
        if with_visit:
            start = at(-1)
            Appointment.objects.create(
                client=client, staff_member=self.staff, service=self.service,
                start=start, end=start + datetime.timedelta(minutes=45),
                status=Appointment.Status.COMPLETED)
        return client

    def test_stdout_matches_service_output(self):
        self._client("Dana", "Due", with_visit=True)
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.id, now=NOW, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_summaries_csv(self.salon, now=NOW))

    def test_stdout_matches_service_output_with_default_now(self):
        self._client("Dana", "Due")
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.id, stdout=out)
        # No fixed instant: compare shape against service called
        # without a client-affecting history (header + one row).
        self.assertTrue(out.getvalue().startswith("client_id,"))
        self.assertIn("Dana", out.getvalue())

    def test_now_string_is_passed_through(self):
        self._client("Dana", "Due", with_visit=True)
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.id,
            now="2026-11-02T12:00:00+00:00", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_summaries_csv(self.salon, now=NOW))

    def test_output_file_matches_service_output(self):
        self._client("Dana", "Due", with_visit=True)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.id, now=NOW,
            output=path, stdout=out)
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(
            data, export_client_summaries_csv(self.salon, now=NOW))
        self.assertEqual(out.getvalue(), "")

    def test_salon_scoping_excludes_other_salons(self):
        self._client("Mina", "Mine")
        self._client("Theo", "Theirs", salon=self.other_salon)
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.id, now=NOW, stdout=out)
        text = out.getvalue()
        self.assertIn("Mina", text)
        self.assertNotIn("Theo", text)
        self.assertEqual(
            text, export_client_summaries_csv(self.salon, now=NOW))

    def test_empty_book_exports_header_only(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.id, now=NOW, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_summaries_csv(self.salon, now=NOW))

    def test_unknown_salon_id_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), salon_id=999999, stdout=io.StringIO())

    def test_salon_id_is_required(self):
        with self.assertRaises(CommandError):
            call_command(_cmd(), stdout=io.StringIO())

    def test_invalid_now_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), salon_id=self.salon.id, now="not-a-date",
                stdout=io.StringIO())

    def test_unwritable_output_raises(self):
        self._client("Dana", "Due")
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), salon_id=self.salon.id, now=NOW,
                output="/nonexistent-dir/out.csv", stdout=io.StringIO())
