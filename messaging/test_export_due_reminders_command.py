"""Tests for the export_due_reminders management command.

The command is a thin wrapper around
``messaging.due_export.export_due_reminders_csv``: these tests
pin that its stdout and file output match that service and
that unknown salons, bad dates, and reversed ranges fail
cleanly as ``CommandError``. Datetime bounds pass verbatim;
plain dates mean whole days in the salon timezone (UTC here).
"""
import datetime
import io
import os
import tempfile
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from messaging.due_export import export_due_reminders_csv
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
DAY = datetime.date(2026, 3, 2)
NEXT = DAY + datetime.timedelta(days=1)
START = datetime.datetime.combine(DAY, datetime.time.min, tzinfo=UTC)
END = datetime.datetime.combine(DAY, datetime.time.max, tzinfo=UTC)
NEXT_END = datetime.datetime.combine(
    NEXT, datetime.time.max, tzinfo=UTC)


class ExportDueRemindersCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts")
        service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        client = Client.objects.create(
            salon=self.salon, first_name="Client1", last_name="Example",
            email="c1@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True)
        start = datetime.datetime.combine(
            DAY, datetime.time(12, 0), tzinfo=UTC)
        Appointment.objects.create(
            client=client, staff_member=staff, service=service,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)

    def test_stdout_matches_service_with_datetime_bounds(self):
        out = io.StringIO()
        call_command(
            "export_due_reminders", salon_id=self.salon.pk,
            start_date=START, end_date=END, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_due_reminders_csv(self.salon, START, END))

    def test_stdout_matches_service_with_date_bounds(self):
        out = io.StringIO()
        call_command(
            "export_due_reminders", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_due_reminders_csv(self.salon, START, END))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_due_reminders",
            "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(),
            "--end-date", NEXT.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_due_reminders_csv(self.salon, START, NEXT_END))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "due_reminders.csv")
            call_command(
                "export_due_reminders", salon_id=self.salon.pk,
                start_date=DAY, end_date=NEXT, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written,
            export_due_reminders_csv(self.salon, START, NEXT_END))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_due_reminders", salon_id=self.salon.pk + 999,
                start_date=DAY, end_date=DAY, stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_due_reminders", salon_id=self.salon.pk,
                start_date="not-a-date", end_date=DAY,
                stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_due_reminders",
                "--salon-id", str(self.salon.pk),
                "--start-date", "2026-13-40",
                "--end-date", DAY.isoformat(), stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_due_reminders", salon_id=self.salon.pk,
                start_date=NEXT, end_date=DAY, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_due_reminders", salon_id=self.salon.pk,
                start_date=END, end_date=START, stdout=io.StringIO())
