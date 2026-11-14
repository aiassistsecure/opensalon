"""Format tests for the send_email_reminders management command.

Mirrors the --format tests for send_due_reminders: the default
and explicit ``text`` output are byte-identical to before,
``json`` prints exactly one JSON object carrying the same
facts (with ``would_send`` naming in dry-run), and an invalid
format raises ``CommandError``. Counts only -- no contact
details are printed in either mode.
"""
import io
import json
from datetime import timedelta

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="salon@example.com",
)
class SendEmailRemindersFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.start = timezone.now() + timedelta(hours=2)

    def _appointment(self, **client_kwargs):
        defaults = dict(
            salon=self.salon, first_name="Test", last_name="Example",
            phone="555-0100", email="client@example.com",
            email_opt_in=True)
        defaults.update(client_kwargs)
        client = Client.objects.create(**defaults)
        return Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            start=self.start, end=self.start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)

    def _seed_mixed(self):
        self._appointment()
        self._appointment(email_opt_in=False, email="optedout@example.com")
        self._appointment(email="", phone="555-0102")

    def _run(self, out, *extra_args):
        call_command(
            "send_email_reminders", "--hours", "24",
            *extra_args, stdout=out)

    def test_default_text_unchanged(self):
        self._seed_mixed()
        out = io.StringIO()
        self._run(out)
        self.assertEqual(
            out.getvalue(),
            "Email reminders: 1 sent, 2 skipped "
            "(1 not opted in, 1 missing email, "
            "0 not remindable status).\n")
        self.assertEqual(len(mail.outbox), 1)

    def test_explicit_text_format_matches_default(self):
        self._seed_mixed()
        out = io.StringIO()
        self._run(out, "--format", "text")
        self.assertEqual(
            out.getvalue(),
            "Email reminders: 1 sent, 2 skipped "
            "(1 not opted in, 1 missing email, "
            "0 not remindable status).\n")
        self.assertEqual(len(mail.outbox), 1)

    def test_dry_run_explicit_text_format_matches_default(self):
        self._seed_mixed()
        out = io.StringIO()
        self._run(out, "--dry-run", "--format", "text")
        self.assertEqual(
            out.getvalue(),
            "Dry run: Email reminders: 1 would send, 2 skipped "
            "(1 not opted in, 1 missing email, "
            "0 not remindable status).\n")
        self.assertEqual(len(mail.outbox), 0)

    def test_json_output_parses_and_carries_facts(self):
        self._seed_mixed()
        out = io.StringIO()
        self._run(out, "--format", "json")
        text = out.getvalue()
        self.assertNotIn("Email reminders:", text)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertEqual(json.loads(text), {
            "sent": 1, "skipped": 2,
            "skipped_not_opted_in": 1,
            "skipped_missing_email": 1,
            "skipped_status": 0,
            "dry_run": False})
        self.assertNotIn("client@example.com", text)
        self.assertNotIn("optedout@example.com", text)
        self.assertEqual(len(mail.outbox), 1)

    def test_dry_run_json_reports_would_send_and_sends_nothing(self):
        self._seed_mixed()
        out = io.StringIO()
        self._run(out, "--dry-run", "--format", "json")
        text = out.getvalue()
        self.assertNotIn("Dry run", text)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertEqual(json.loads(text), {
            "would_send": 1, "skipped": 2,
            "skipped_not_opted_in": 1,
            "skipped_missing_email": 1,
            "skipped_status": 0,
            "dry_run": True})
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_format_rejected(self):
        self._seed_mixed()
        with self.assertRaises(CommandError):
            call_command(
                "send_email_reminders", hours=24, format="bogus",
                stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 0)
