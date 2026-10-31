"""Tests for the export_noshow management command.

The command is a thin wrapper around
``bookings.noshow_export.export_noshow_csv``: these tests pin
that its stdout and file output match that service verbatim,
that it scopes to the requested salon, and that unknown salons,
missing dates, and unwritable output fail cleanly.
Fixtures are tiny synthetic records -- unit logic only. The
fixture day is in the past so the no-show service (which only
counts past appointments) includes it under its default ``now``.
"""
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from bookings.noshow_export import export_noshow_csv
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 10, 26)  # a Monday, in the past
NEXT_DAY = DAY + datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC)


class ExportNoshowCommandTests(TestCase):
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
            start=at(DAY, 9), end=at(DAY, 9, 45),
            status=Appointment.Status.NO_SHOW)
        Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service,
            start=at(DAY, 11), end=at(DAY, 11, 45),
            status=Appointment.Status.COMPLETED)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_noshow", salon_id=self.salon.pk,
            date_from=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_noshow_csv(self.salon, DAY, None))
        self.assertIn("no_show", out.getvalue())
        self.assertNotIn("completed", out.getvalue())

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_noshow", "--salon-id", str(self.salon.pk),
            "--date-from", DAY.isoformat(),
            "--date-to", DAY.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(), export_noshow_csv(self.salon, DAY, DAY))

    def test_stdout_matches_service_with_date_range(self):
        out = io.StringIO()
        call_command(
            "export_noshow", salon_id=self.salon.pk,
            date_from=DAY, date_to=NEXT_DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_noshow_csv(self.salon, DAY, NEXT_DAY))

    def test_salon_scoping(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        other_staff = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        other_client = Client.objects.create(
            salon=other, first_name="Other", last_name="Guest")
        Appointment.objects.create(
            client=other_client, staff_member=other_staff,
            service=self.service,
            start=at(DAY, 10), end=at(DAY, 10, 45),
            status=Appointment.Status.NO_SHOW)
        out = io.StringIO()
        call_command(
            "export_noshow", salon_id=self.salon.pk,
            date_from=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_noshow_csv(self.salon, DAY, None))
        self.assertIn("Stylist One", out.getvalue())
        self.assertNotIn("Other Stylist", out.getvalue())

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "noshow.csv")
            call_command(
                "export_noshow", salon_id=self.salon.pk,
                date_from=DAY, date_to=DAY, output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_noshow_csv(self.salon, DAY, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_noshow", salon_id=self.salon.pk + 1000,
                date_from=DAY, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "noshow.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_noshow", salon_id=self.salon.pk,
                    date_from=DAY, output=path, stdout=io.StringIO())

    def test_no_date_from_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_noshow", salon_id=self.salon.pk,
                stdout=io.StringIO())

    def test_bad_date_from_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_noshow",
                "--salon-id", str(self.salon.pk),
                "--date-from", "not-a-date", stdout=io.StringIO())

    def test_bad_date_to_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_noshow",
                "--salon-id", str(self.salon.pk),
                "--date-from", DAY.isoformat(),
                "--date-to", "not-a-date", stdout=io.StringIO())
