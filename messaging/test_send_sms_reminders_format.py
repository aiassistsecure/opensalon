"""Tests for --format on the send_sms_reminders command.

Mirrors the format tests for send_due_reminders: default
text is unchanged, explicit text matches default, json
prints exactly one object carrying the same facts as the
text output (with would_send naming in dry-run), and an
invalid format raises CommandError.
"""
import io
import json
from datetime import timedelta
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.adapters import SmsAdapter, SmsResult
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember


class FakeSmsAdapter(SmsAdapter):
    name = "fake"

    def __init__(self):
        self.calls = []

    def send_sms(self, to, body):
        self.calls.append((to, body))
        return SmsResult(success=True, status="sent", reference="fake-1")


class SendSmsRemindersFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.start = timezone.now() + timedelta(hours=2)
        self._appointment(sms_opt_in=True, phone="555-0100")
        self._appointment(sms_opt_in=False, phone="555-0101")
        self.adapter = FakeSmsAdapter()

    def _appointment(self, **kw):
        client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example",
            email="client@example.com", **kw)
        return Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            start=self.start, end=self.start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)

    def _run(self, out, *extra_args):
        with mock.patch(
            "messaging.reminders.get_sms_adapter",
            return_value=self.adapter
        ):
            call_command(
                "send_sms_reminders", "--hours", "24",
                *extra_args, stdout=out)

    def test_default_text_unchanged(self):
        out = io.StringIO()
        self._run(out)
        self.assertEqual(
            out.getvalue(),
            "SMS reminders: 1 sent, 1 skipped "
            "(1 not opted in, 0 missing phone, "
            "0 not remindable status, 0 send failed).\n")
        self.assertEqual(len(self.adapter.calls), 1)

    def test_explicit_text_format_matches_default(self):
        out = io.StringIO()
        self._run(out, "--format", "text")
        self.assertEqual(
            out.getvalue(),
            "SMS reminders: 1 sent, 1 skipped "
            "(1 not opted in, 0 missing phone, "
            "0 not remindable status, 0 send failed).\n")
        self.assertEqual(len(self.adapter.calls), 1)

    def test_dry_run_explicit_text_format_matches_default(self):
        out = io.StringIO()
        self._run(out, "--dry-run", "--format", "text")
        self.assertEqual(
            out.getvalue(),
            "Dry run: SMS reminders: 1 would send, 1 skipped "
            "(1 not opted in, 0 missing phone, "
            "0 not remindable status, 0 send failed).\n")
        self.assertEqual(self.adapter.calls, [])

    def test_json_output_parses_and_carries_facts(self):
        out = io.StringIO()
        self._run(out, "--format", "json")
        text = out.getvalue()
        self.assertNotIn("SMS reminders:", text)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertEqual(json.loads(text), {
            "sent": 1, "skipped": 1,
            "skipped_not_opted_in": 1,
            "skipped_missing_phone": 0,
            "skipped_status": 0,
            "skipped_send_failed": 0,
            "dry_run": False})
        self.assertNotIn("555-0100", text)
        self.assertNotIn("555-0101", text)
        self.assertEqual(len(self.adapter.calls), 1)

    def test_dry_run_json_reports_dry_run_and_sends_nothing(self):
        out = io.StringIO()
        self._run(out, "--dry-run", "--format", "json")
        text = out.getvalue()
        self.assertNotIn("Dry run", text)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertEqual(json.loads(text), {
            "would_send": 1, "skipped": 1,
            "skipped_not_opted_in": 1,
            "skipped_missing_phone": 0,
            "skipped_status": 0,
            "skipped_send_failed": 0,
            "dry_run": True})
        self.assertEqual(self.adapter.calls, [])

    def test_invalid_format_rejected(self):
        with mock.patch(
            "messaging.reminders.get_sms_adapter",
            return_value=self.adapter
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "send_sms_reminders", hours=24, format="bogus",
                    stdout=io.StringIO())
        self.assertEqual(self.adapter.calls, [])
