"""Tests for the export_upcoming management command.

The command is a thin wrapper around
``bookings.upcoming_export.export_upcoming_csv``: these tests
pin that its stdout and file output match that service verbatim
and that unknown salons and bad arguments fail cleanly.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from bookings.upcoming import DEFAULT_DAYS
from bookings.upcoming_export import export_upcoming_csv
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc
START = datetime.datetime.combine(DAY, datetime.time.min, tzinfo=UTC)


class ExportUpcomingCommandTests(TestCase):
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
            "export_upcoming", salon_id=self.salon.pk, start=DAY,
            days=7, stdout=out)
        self.assertEqual(
            out.getvalue(), export_upcoming_csv(self.salon, DAY, 7))

    def test_stdout_matches_service_with_string_args(self):
        out = io.StringIO()
        call_command(
            "export_upcoming", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--days", "7", stdout=out)
        self.assertEqual(
            out.getvalue(), export_upcoming_csv(self.salon, DAY, 7))

    def test_stdout_defaults_match_service(self):
        out = io.StringIO()
        call_command(
            "export_upcoming", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_upcoming_csv(self.salon, None, DEFAULT_DAYS))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "upcoming.csv")
            call_command(
                "export_upcoming", salon_id=self.salon.pk, start=DAY,
                days=7, output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(written, export_upcoming_csv(self.salon, DAY, 7))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_upcoming", salon_id=self.salon.pk + 1000,
                start=DAY, stdout=io.StringIO())

    def test_bad_start_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_upcoming", "--salon-id", str(self.salon.pk),
                "--start-date", "not-a-date", stdout=io.StringIO())

    def test_bad_days_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_upcoming", "--salon-id", str(self.salon.pk),
                "--days", "not-a-number", stdout=io.StringIO())
