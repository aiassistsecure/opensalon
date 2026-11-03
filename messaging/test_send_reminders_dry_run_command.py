"""Tests for --dry-run on the three reminder sender commands.

Dry-run must resolve the same due set and per-channel opt-in
gates as the real send, report would-send / skipped-by-opt-in
counts, send nothing, and write no ReminderSend rows. Non-dry-run
behaviour is pinned unchanged (sends + rows).
"""
import io
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.adapters import SmsAdapter, SmsResult
from messaging.models import ReminderSend
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember


class FakeSmsAdapter(SmsAdapter):
    name = "fake"

    def __init__(self):
        self.calls = []

    def send_sms(self, to, body):
        self.calls.append((to, body))
        return SmsResult(success=True, status="sent", reference="fake-1")


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="salon@example.com",
)
class DryRunReminderCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.start = timezone.now() + timedelta(hours=2)
        # One both-opted-in, one neither-opted-in appointment.
        self._appointment(sms_opt_in=True, email_opt_in=True,
                          email="a@example.com", phone="555-0100")
        self._appointment(sms_opt_in=False, email_opt_in=False,
                          email="b@example.com", phone="555-0101")
        self.adapter = FakeSmsAdapter()

    def _appointment(self, **kw):
        client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example", **kw)
        return Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            start=self.start, end=self.start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)

    def _run(self, command, *extra):
        out = io.StringIO()
        with mock.patch("messaging.reminders.get_sms_adapter",
                        return_value=self.adapter):
            call_command(command, "--hours", "24", *extra, stdout=out)
        return out.getvalue()

    def _assert_nothing_sent(self):
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(ReminderSend.objects.count(), 0)

    def test_email_dry_run(self):
        text = self._run("send_email_reminders", "--dry-run")
        self._assert_nothing_sent()
        self.assertIn("Dry run", text)
        self.assertIn("1 would send", text)
        self.assertIn("1 not opted in", text)

    def test_sms_dry_run(self):
        text = self._run("send_sms_reminders", "--dry-run")
        self._assert_nothing_sent()
        self.assertIn("Dry run", text)
        self.assertIn("1 would send", text)
        self.assertIn("1 not opted in", text)

    def test_combined_dry_run_counts_by_channel(self):
        text = self._run("send_due_reminders", "--dry-run")
        self._assert_nothing_sent()
        self.assertIn("Dry run", text)
        self.assertIn("2 would send", text)
        self.assertIn("2 skipped by opt-in", text)
        self.assertIn("email: 1 would send", text)
        self.assertIn("SMS: 1 would send", text)

    def test_email_non_dry_run_unchanged(self):
        text = self._run("send_email_reminders")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(ReminderSend.objects.filter(
            channel="email").count(), 1)
        self.assertIn("1 sent", text)
        self.assertNotIn("Dry run", text)

    def test_sms_non_dry_run_unchanged(self):
        text = self._run("send_sms_reminders")
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(ReminderSend.objects.filter(
            channel="sms").count(), 1)
        self.assertIn("1 sent", text)

    def test_combined_non_dry_run_unchanged(self):
        text = self._run("send_due_reminders")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(ReminderSend.objects.count(), 2)
        self.assertIn("2 sent", text)
