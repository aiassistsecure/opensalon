"""Tests for the export_cancellations management command.

The command is a thin wrapper around
``onlinebooking.cancellations_export.export_cancellations_csv``:
these tests pin that its stdout and file output match that
service verbatim, that its arguments forward to the service,
and that an unknown salon, bad dates, and a reversed range
fail cleanly as ``CommandError``. Fixtures are tiny synthetic
records -- unit logic only.
"""
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.cancellations_export import export_cancellations_csv
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
D1 = datetime.date(2026, 11, 2)
D2 = datetime.date(2026, 11, 3)
D3 = datetime.date(2026, 11, 4)


def at(day, hour=10):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


class ExportCancellationsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Alice")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=60)
        Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(D1), end=at(D1, 11),
            status="cancelled", origin="online")

    def run_export(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("salon_id", self.salon.pk)
        call_command("export_cancellations", stdout=out, **kwargs)
        return out.getvalue()

    def test_stdout_matches_service(self):
        out = self.run_export(date_from=D1, date_to=D3)
        self.assertEqual(
            out, export_cancellations_csv(self.salon, D1, D3))
        self.assertIn("Alice", out)

    def test_stdout_matches_service_with_string_args(self):
        out = io.StringIO()
        call_command(
            "export_cancellations", "--salon-id", str(self.salon.pk),
            "--date-from", D1.isoformat(), "--date-to", D3.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_cancellations_csv(self.salon, D1, D3))

    def test_stdout_matches_service_with_alias_args(self):
        out = io.StringIO()
        call_command(
            "export_cancellations", "--salon-id", str(self.salon.pk),
            "--start-date", D1.isoformat(), "--end-date", D3.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_cancellations_csv(self.salon, D1, D3))

    def test_stdout_matches_service_without_range(self):
        out = self.run_export()
        self.assertEqual(
            out, export_cancellations_csv(self.salon, None, None))
        self.assertEqual(out, export_cancellations_csv(self.salon))

    def test_output_file_matches_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cancellations.csv")
            out = self.run_export(
                date_from=D1, date_to=D3, output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    fh.read(),
                    export_cancellations_csv(self.salon, D1, D3))

    def test_date_range_forwards_to_service(self):
        out = self.run_export(date_from=D2, date_to=D3)
        self.assertEqual(
            out, export_cancellations_csv(self.salon, D2, D3))
        self.assertNotEqual(
            out, export_cancellations_csv(self.salon, D1, D3))

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(salon_id=self.salon.pk + 999)

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(date_from="not-a-date", date_to=D3)
        with self.assertRaises(CommandError):
            self.run_export(date_from=D1, date_to="2026-13-40")

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(date_from=D3, date_to=D1)
