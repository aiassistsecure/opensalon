"""Tests for the export_send_search management command.

The command is a thin wrapper around
``messaging.send_search_export.export_search_sends_csv``: these
tests pin that its stdout and file output match that service
verbatim, that salon scoping is honoured, and that unknown
salons and unwritable outputs fail cleanly as ``CommandError``.
"""
import io
import os
import tempfile
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.models import ReminderSend
from messaging.send_search_export import export_search_sends_csv
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
DAY1 = date(2026, 3, 2)
DAY2 = date(2026, 3, 3)


def _at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=UTC)


class ExportSendSearchCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other Stylist")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.alice = self._send("Alice", "Smith", "email", _at(DAY1, 9))
        self.alice_sms = self._send("Alice", "Brown", "sms", _at(DAY2, 9))
        self._send("Alice", "Smith", "email", _at(DAY1, 10),
                   salon=self.other, staff=self.other_staff)

    def _send(self, first, last, channel, when, salon=None, staff=None):
        salon = salon or self.salon
        staff = staff or self.staff
        client = Client.objects.create(
            salon=salon, first_name=first, last_name=last,
            email="c@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True)
        start = timezone.now() + timedelta(days=1)
        appt = Appointment.objects.create(
            client=client, staff_member=staff, service=self.service,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)
        return ReminderSend.objects.create(
            appointment=appt, client=client, channel=channel,
            status="sent", sent_at=when)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_send_search", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(
            out.getvalue(), export_search_sends_csv(self.salon))

    def test_stdout_matches_service_with_filters(self):
        out = io.StringIO()
        call_command(
            "export_send_search", "--salon-id", str(self.salon.pk),
            "--term", "alice", "--channel", "sms",
            "--status", "sent", "--start", DAY2.isoformat(),
            "--end", DAY2.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_search_sends_csv(
                self.salon, "alice", channel="sms", status="sent",
                start=DAY2, end=DAY2))

    def test_stdout_matches_service_with_kwargs_filters(self):
        out = io.StringIO()
        call_command(
            "export_send_search", salon_id=self.salon.pk, term="smith",
            channel="email", start=DAY1, end=DAY1, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_search_sends_csv(
                self.salon, "smith", channel="email",
                start=DAY1, end=DAY1))

    def test_salon_scoping(self):
        out = io.StringIO()
        call_command(
            "export_send_search", salon_id=self.salon.pk,
            term="alice", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_search_sends_csv(self.salon, "alice"))
        # Header + this salon's two Alice sends only.
        self.assertEqual(len(out.getvalue().strip().splitlines()), 3)
        other_out = io.StringIO()
        call_command(
            "export_send_search", salon_id=self.other.pk,
            term="alice", stdout=other_out)
        self.assertEqual(
            other_out.getvalue(),
            export_search_sends_csv(self.other, "alice"))
        self.assertEqual(
            len(other_out.getvalue().strip().splitlines()), 2)

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "send_search.csv")
            call_command(
                "export_send_search", salon_id=self.salon.pk,
                term="alice", output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_search_sends_csv(self.salon, "alice"))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_send_search", salon_id=self.salon.pk + 1000,
                stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "send_search.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_send_search", salon_id=self.salon.pk,
                    output=path, stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_send_search", salon_id=self.salon.pk,
                start=DAY2, end=DAY1, stdout=io.StringIO())
