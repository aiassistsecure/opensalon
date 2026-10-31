import datetime
import io
import os
import tempfile
from datetime import time, timedelta
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.history_export import export_history_summary_csv
from messaging.models import ReminderSend
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
DAY = datetime.date(2026, 3, 2)
NEXT = DAY + datetime.timedelta(days=1)


class ExportMessageHistoryCommandTests(TestCase):
    def setUp(self):
        salon = Salon.objects.create(name="Example Salon")
        staff = StaffMember.objects.create(
            salon=salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(
            salon=salon, name="Haircuts")
        service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        client = Client.objects.create(
            salon=salon, first_name="Client1", last_name="Example",
            email="c1@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True)
        start = timezone.now() + timedelta(days=1)
        appt = Appointment.objects.create(
            client=client, staff_member=staff, service=service,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)
        ReminderSend.objects.create(
            appointment=appt, client=client, channel="email",
            status=ReminderSend.Status.SENT,
            sent_at=datetime.datetime.combine(
                DAY, time(9), tzinfo=UTC))

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_message_history",
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_history_summary_csv(DAY, DAY))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_message_history",
            "--start-date", DAY.isoformat(),
            "--end-date", NEXT.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(), export_history_summary_csv(DAY, NEXT))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "message_history.csv")
            call_command(
                "export_message_history",
                start_date=DAY, end_date=NEXT, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_history_summary_csv(DAY, NEXT))
        self.assertEqual(out.getvalue(), "")

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_message_history",
                start_date="not-a-date", end_date=DAY,
                stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_message_history",
                "--start-date", "2026-13-40",
                "--end-date", DAY.isoformat(), stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_message_history",
                start_date=NEXT, end_date=DAY, stdout=io.StringIO())
