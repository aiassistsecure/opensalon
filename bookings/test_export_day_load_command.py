"""Tests for the export_day_load management command.

The command is a thin wrapper around
``bookings.day_load_export.export_day_load_csv``: these tests
pin that its stdout and file output match that service verbatim,
that it scopes to the requested salon, and that unknown salons,
missing dates, and unwritable output fail cleanly.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.day_load_export import export_day_load_csv
from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


class ExportDayLoadCommandTests(TestCase):
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
            "export_day_load", salon_id=self.salon.pk,
            date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_day_load_csv(self.salon, DAY))

    def test_stdout_matches_service_with_string_date_arg(self):
        out = io.StringIO()
        call_command(
            "export_day_load", "--salon-id", str(self.salon.pk),
            "--date", DAY.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(), export_day_load_csv(self.salon, DAY))

    def test_salon_scoping(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        other_staff = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        Appointment.objects.create(
            client=self.client, staff_member=other_staff,
            service=self.service,
            start=datetime.datetime.combine(
                DAY, datetime.time(10, 0), tzinfo=UTC),
            end=datetime.datetime.combine(
                DAY, datetime.time(11, 0), tzinfo=UTC))
        out = io.StringIO()
        call_command(
            "export_day_load", salon_id=other.pk,
            date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_day_load_csv(other, DAY))
        self.assertIn("Other Stylist", out.getvalue())
        self.assertNotIn("Stylist One", out.getvalue())

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "day_load.csv")
            call_command(
                "export_day_load", salon_id=self.salon.pk,
                date=DAY, output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_day_load_csv(self.salon, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_day_load", salon_id=self.salon.pk + 1000,
                date=DAY, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "day_load.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_day_load", salon_id=self.salon.pk,
                    date=DAY, output=path, stdout=io.StringIO())

    def test_no_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_day_load", salon_id=self.salon.pk,
                stdout=io.StringIO())

    def test_bad_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_day_load",
                "--salon-id", str(self.salon.pk),
                "--date", "not-a-date", stdout=io.StringIO())
