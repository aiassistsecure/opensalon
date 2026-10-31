"""Tests for the export_status management command.

The command is a thin wrapper around
``bookings.status_export.export_status_counts_csv``: these tests
pin that its stdout and file output match that service verbatim,
that it scopes to the requested salon, and that unknown salons,
service errors, and unwritable output fail cleanly.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from bookings.status_export import export_status_counts_csv
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


class ExportStatusCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service,
            start=datetime.datetime.combine(
                DAY, datetime.time(9, 0), tzinfo=UTC),
            end=datetime.datetime.combine(
                DAY, datetime.time(9, 45), tzinfo=UTC))

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_status", salon_id=self.salon.pk, date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_status_counts_csv(self.salon, DAY))

    def test_stdout_matches_service_with_string_date_arg(self):
        out = io.StringIO()
        call_command(
            "export_status", "--salon-id", str(self.salon.pk),
            "--date", DAY.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(), export_status_counts_csv(self.salon, DAY))

    def test_range_passes_through_to_service(self):
        last = DAY + datetime.timedelta(days=1)
        out = io.StringIO()
        call_command(
            "export_status", salon_id=self.salon.pk,
            date_from=DAY, date_to=last, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_status_counts_csv(
                self.salon, date_from=DAY, date_to=last))

    def test_salon_scoping(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        other_staff = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        other_client = Client.objects.create(
            salon=other, first_name="Other", last_name="Client")
        Appointment.objects.create(
            client=other_client, staff_member=other_staff,
            service=self.service,
            start=datetime.datetime.combine(
                DAY, datetime.time(10, 0), tzinfo=UTC),
            end=datetime.datetime.combine(
                DAY, datetime.time(10, 45), tzinfo=UTC))
        out = io.StringIO()
        call_command(
            "export_status", salon_id=other.pk, date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_status_counts_csv(other, DAY))
        self.assertNotEqual(
            out.getvalue(), export_status_counts_csv(self.salon, DAY))
        self.assertIn(f"{other.pk},", out.getvalue())

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "status.csv")
            call_command(
                "export_status", salon_id=self.salon.pk, date=DAY,
                output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(written, export_status_counts_csv(self.salon, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_status", salon_id=self.salon.pk + 1000,
                date=DAY, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "status.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_status", salon_id=self.salon.pk, date=DAY,
                    output=path, stdout=io.StringIO())

    def test_no_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_status", salon_id=self.salon.pk,
                stdout=io.StringIO())
