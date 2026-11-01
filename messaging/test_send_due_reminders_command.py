"""Tests for the send_due_reminders management command.

The command is a thin wrapper around
``messaging.dispatch.send_due_reminders``: these tests pin
that it dispatches through that combined service, reports
counts only (no contact details), respects per-channel
opt-ins exactly as the service does, is registered to the
messaging app, and fails cleanly as ``CommandError``.
"""
import io
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
