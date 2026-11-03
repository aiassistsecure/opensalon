"""Tests for --now on the three reminder sender commands.

``--now`` pins the reference instant each command's window is
measured from: it is parsed from ISO-8601 to an aware datetime
and passed through to the existing service (``now=``), so a
run can be replayed for a chosen instant. When omitted, the
service's own default applies -- today's clock, exactly as
before this flag existed.
"""
import datetime
import io
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.adapters import SmsAdapter, SmsResult
from messaging.dispatch import ReminderDispatchSummary
from messaging.email_reminders import EmailDeliverySummary
from messaging.sms_reminders import SmsDeliverySummary
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
class SendRemindersNowCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.ref = timezone.now()
        self.start = self.ref + timedelta(hours=2)
        client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example",
            phone="555-0100", email="client@example.com",
            sms_opt_in=True, email_opt_in=True)
        Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            start=self.start, end=self.start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)
        self.adapter = FakeSmsAdapter()

    def _run(self, command, *extra_args, **kwargs):
        out = io.StringIO()
        with mock.patch("messaging.reminders.get_sms_adapter",
                        return_value=self.adapter):
            call_command(command, *extra_args, stdout=out, **kwargs)
        return out.getvalue()

    # -- behaviour: the pinned instant moves the window ---------

    def test_email_now_inside_window_sends(self):
        text = self._run("send_email_reminders", "--hours", "24",
                         "--now", self.ref.isoformat())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("1 sent", text)

    def test_email_now_before_window_sends_nothing(self):
        early = (self.ref - timedelta(days=2)).isoformat()
        text = self._run("send_email_reminders", "--hours", "24",
                         "--now", early)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("0 sent", text)

    def test_sms_now_inside_window_sends(self):
        text = self._run("send_sms_reminders", "--hours", "24",
                         "--now", self.ref.isoformat())
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertIn("1 sent", text)

    def test_sms_now_after_window_sends_nothing(self):
        late = (self.ref + timedelta(days=2)).isoformat()
        text = self._run("send_sms_reminders", "--hours", "24",
                         "--now", late)
        self.assertEqual(self.adapter.calls, [])
        self.assertIn("0 sent", text)

    def test_combined_now_inside_window_sends_both(self):
        text = self._run("send_due_reminders", "--hours", "24",
                         "--now", self.ref.isoformat())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertIn("2 sent", text)

    def test_combined_now_before_window_sends_nothing(self):
        early = (self.ref - timedelta(days=2)).isoformat()
        text = self._run("send_due_reminders", "--hours", "24",
                         "--now", early)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.adapter.calls, [])
        self.assertIn("0 sent", text)

    def test_now_z_suffix_and_naive_are_aware_equivalents(self):
        zulu = self.ref.astimezone(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        text = self._run("send_email_reminders", "--hours", "24",
                         "--now", zulu)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("1 sent", text)

    def test_now_kwargs_datetime_and_string_match_cli(self):
        for value in (self.ref, self.ref.isoformat()):
            mail.outbox.clear()
            text = self._run("send_email_reminders", now=value)
            self.assertEqual(len(mail.outbox), 1)
            self.assertIn("1 sent", text)

    def test_omitted_now_uses_todays_clock(self):
        # Appointment starts 2h from real now: omitted --now sends.
        text = self._run("send_due_reminders", "--hours", "24")
        self.assertIn("2 sent", text)

    def test_now_with_dry_run_counts_would_send(self):
        text = self._run("send_email_reminders", "--hours", "24",
                         "--now", self.ref.isoformat(), "--dry-run")
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("1 would send", text)

    # -- passthrough: the service receives the parsed instant --

    def test_email_service_receives_parsed_aware_now(self):
        target = ("messaging.management.commands.send_email_reminders"
                  ".send_due_email_reminders")
        with mock.patch(target, return_value=EmailDeliverySummary()) as svc:
            call_command("send_email_reminders", "--hours", "24",
                         "--now", self.ref.isoformat(),
                         stdout=io.StringIO())
        kwargs = svc.call_args.kwargs
        self.assertEqual(kwargs["now"], self.ref)
        self.assertIsNotNone(kwargs["now"].tzinfo)
        self.assertEqual(kwargs["within"], timedelta(hours=24))

    def test_sms_service_receives_parsed_aware_now(self):
        target = ("messaging.management.commands.send_sms_reminders"
                  ".send_due_sms_reminders")
        with mock.patch(target, return_value=SmsDeliverySummary()) as svc:
            call_command("send_sms_reminders", "--hours", "24",
                         "--now", self.ref.isoformat(),
                         stdout=io.StringIO())
        kwargs = svc.call_args.kwargs
        self.assertEqual(kwargs["now"], self.ref)
        self.assertIsNotNone(kwargs["now"].tzinfo)

    def test_combined_service_receives_none_when_omitted(self):
        target = ("messaging.management.commands.send_due_reminders"
                  ".send_due_reminders")
        summary = ReminderDispatchSummary(
            email=EmailDeliverySummary(), sms=SmsDeliverySummary())
        with mock.patch(target, return_value=summary) as svc:
            call_command("send_due_reminders", "--hours", "24",
                         stdout=io.StringIO())
        self.assertIsNone(svc.call_args.kwargs["now"])

    # -- invalid input -------------------------------------------

    def test_bad_now_raises_command_error_all_commands(self):
        for command in ("send_due_reminders", "send_email_reminders",
                        "send_sms_reminders"):
            with self.assertRaises(CommandError, msg=command):
                call_command(command, "--now", "not-a-datetime",
                             stdout=io.StringIO())
            with self.assertRaises(CommandError, msg=command):
                call_command(command, now="not-a-datetime",
                             stdout=io.StringIO())
