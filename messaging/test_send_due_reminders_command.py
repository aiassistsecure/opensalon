"""Tests for the send_due_reminders management command.

The command is a thin wrapper around
``messaging.dispatch.send_due_reminders``: these tests pin
that it dispatches through that combined service, reports
counts only (no contact details), respects per-channel
opt-ins exactly as the service does, is registered to the
messaging app, and fails cleanly as ``CommandError``.
"""
import io
import json
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.core.management import CommandError, call_command, get_commands
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.adapters import SmsAdapter, SmsResult
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember


class FakeSmsAdapter(SmsAdapter):
    """Test double satisfying the adapter interface."""

    name = "fake"

    def __init__(self, success=True):
        self.calls = []
        self.success = success

    def send_sms(self, to, body):
        self.calls.append((to, body))
        if not self.success:
            return SmsResult(success=False, status="failed",
                             message="adapter_failed")
        return SmsResult(success=True, status="sent", reference="fake-1")


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="salon@example.com",
)
class SendDueRemindersCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        self.now = timezone.now()
        self.start = self.now + timedelta(hours=2)

    def _appointment(self, **client_kwargs):
        defaults = dict(
            salon=self.salon, first_name="Test", last_name="Example",
            phone="555-0100", email="client@example.com",
            sms_opt_in=False, email_opt_in=False,
        )
        defaults.update(client_kwargs)
        client = Client.objects.create(**defaults)
        return Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            start=self.start, end=self.start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED,
        )

    def _run(self, adapter, out, *extra_args):
        with mock.patch(
            "messaging.reminders.get_sms_adapter", return_value=adapter
        ):
            call_command(
                "send_due_reminders", "--hours", "24",
                *extra_args, stdout=out)

    def test_command_registered_to_messaging_app(self):
        self.assertEqual(get_commands()["send_due_reminders"], "messaging")

    def test_both_opted_in_gets_both_and_reports_counts_only(self):
        self._appointment(sms_opt_in=True, email_opt_in=True)
        adapter = FakeSmsAdapter()
        out = io.StringIO()
        self._run(adapter, out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["client@example.com"])
        self.assertEqual([c[0] for c in adapter.calls], ["555-0100"])
        text = out.getvalue()
        self.assertIn("2 sent", text)
        self.assertIn("0 skipped", text)
        self.assertIn("email: 1 sent", text)
        self.assertIn("SMS: 1 sent", text)
        self.assertNotIn("555-0100", text)
        self.assertNotIn("client@example.com", text)

    def test_neither_opted_in_gets_nothing(self):
        self._appointment(sms_opt_in=False, email_opt_in=False)
        adapter = FakeSmsAdapter()
        out = io.StringIO()
        self._run(adapter, out)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(adapter.calls, [])
        text = out.getvalue()
        self.assertIn("0 sent", text)
        self.assertIn("2 skipped", text)

    def test_email_only_opt_in_gets_email_only(self):
        self._appointment(email_opt_in=True, sms_opt_in=False)
        adapter = FakeSmsAdapter()
        out = io.StringIO()
        self._run(adapter, out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(adapter.calls, [])
        text = out.getvalue()
        self.assertIn("1 sent", text)
        self.assertIn("email: 1 sent", text)
        self.assertIn("SMS: 0 sent", text)

    def test_negative_hours_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "send_due_reminders", "--hours", "-1",
                stdout=io.StringIO())

    def test_service_error_raises_command_error(self):
        with mock.patch(
            "messaging.management.commands.send_due_reminders"
            ".send_due_reminders",
            side_effect=ValueError("bad window"),
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "send_due_reminders", "--hours", "24",
                    stdout=io.StringIO())

    def test_explicit_text_format_matches_default(self):
        self._appointment(sms_opt_in=True, email_opt_in=True)
        adapter = FakeSmsAdapter()
        out = io.StringIO()
        self._run(adapter, out, "--format", "text")
        self.assertEqual(
            out.getvalue(),
            "Reminders: 2 sent, 0 skipped "
            "(email: 1 sent, 0 skipped; "
            "SMS: 1 sent, 0 skipped).\n")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(adapter.calls), 1)

    def test_dry_run_explicit_text_format_matches_default(self):
        self._appointment(sms_opt_in=True, email_opt_in=True)
        self._appointment(
            sms_opt_in=False, email_opt_in=False,
            phone="555-0101", email="other@example.com")
        adapter = FakeSmsAdapter()
        out = io.StringIO()
        self._run(adapter, out, "--dry-run", "--format", "text")
        self.assertEqual(
            out.getvalue(),
            "Dry run: Reminders: 2 would send, 2 skipped "
            "(2 skipped by opt-in; email: 1 would send, 1 skipped; "
            "SMS: 1 would send, 1 skipped).\n")
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(adapter.calls, [])

    def test_json_output_parses_and_carries_facts(self):
        self._appointment(sms_opt_in=True, email_opt_in=True)
        adapter = FakeSmsAdapter()
        out = io.StringIO()
        self._run(adapter, out, "--format", "json")
        text = out.getvalue()
        self.assertNotIn("Reminders:", text)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertEqual(json.loads(text), {
            "sent": 2, "skipped": 0,
            "email_sent": 1, "email_skipped": 0,
            "sms_sent": 1, "sms_skipped": 0,
            "dry_run": False})
        self.assertNotIn("555-0100", text)
        self.assertNotIn("client@example.com", text)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual([c[0] for c in adapter.calls], ["555-0100"])

    def test_dry_run_json_reports_dry_run_and_sends_nothing(self):
        self._appointment(sms_opt_in=True, email_opt_in=True)
        self._appointment(
            sms_opt_in=False, email_opt_in=False,
            phone="555-0101", email="other@example.com")
        adapter = FakeSmsAdapter()
        out = io.StringIO()
        self._run(adapter, out, "--dry-run", "--format", "json")
        text = out.getvalue()
        self.assertNotIn("Dry run", text)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertEqual(json.loads(text), {
            "would_send": 2, "skipped": 2, "skipped_by_opt_in": 2,
            "email_would_send": 1, "email_skipped": 1,
            "sms_would_send": 1, "sms_skipped": 1,
            "dry_run": True})
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(adapter.calls, [])

    def test_json_errors_still_command_error(self):
        self._appointment(sms_opt_in=True, email_opt_in=True)
        adapter = FakeSmsAdapter()
        with mock.patch(
            "messaging.reminders.get_sms_adapter", return_value=adapter
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "send_due_reminders", hours=24, format="bogus",
                    stdout=io.StringIO())
            with self.assertRaises(CommandError):
                call_command(
                    "send_due_reminders", "--hours", "-1",
                    "--format", "json", stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(adapter.calls, [])
