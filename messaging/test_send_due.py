from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.adapters import SmsAdapter, SmsResult
from messaging.dispatch import ReminderDispatchSummary
from messaging.due import due_reminders
from messaging.send_due import SendDueSummary, send_due, send_due_reminders_between
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember


class FakeSmsAdapter(SmsAdapter):
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
class SendDueTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Haircuts")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        self.window_start = timezone.now() + timedelta(hours=1)
        self.window_end = self.window_start + timedelta(hours=24)
        self.start = self.window_start + timedelta(hours=2)

    def _appointment(self, start=None, status=Appointment.Status.BOOKED,
                     **client_kwargs):
        defaults = dict(
            salon=self.salon, first_name="Test", last_name="Example",
            phone="555-0100", email="client@example.com",
            email_opt_in=True, sms_opt_in=True,
        )
        defaults.update(client_kwargs)
        client = Client.objects.create(**defaults)
        start = start or self.start
        return Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            start=start, end=start + timedelta(minutes=45), status=status,
        )

    def test_both_opted_in_gets_both_channels(self):
        self._appointment()
        adapter = FakeSmsAdapter()
        summary = send_due(self.window_start, self.window_end, adapter=adapter)
        self.assertIsInstance(summary, SendDueSummary)
        self.assertIsInstance(summary.dispatch, ReminderDispatchSummary)
        self.assertEqual(summary.considered, 1)
        self.assertEqual(summary.dispatched, 1)
        self.assertEqual(summary.sent, 2)
        self.assertEqual(summary.skipped, 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual([c[0] for c in adapter.calls], ["555-0100"])

    def test_email_only_and_sms_only_are_independent(self):
        self._appointment(email="e@example.com", phone="555-0111",
                          sms_opt_in=False)
        self._appointment(email="s@example.com", phone="555-0112",
                          email_opt_in=False)
        adapter = FakeSmsAdapter()
        summary = send_due_reminders_between(
            self.window_start, self.window_end, adapter=adapter
        )
        self.assertEqual(summary.sent, 2)
        self.assertEqual(summary.dispatch.email.sent, 1)
        self.assertEqual(summary.dispatch.sms.sent, 1)
        self.assertEqual([m.to[0] for m in mail.outbox], ["e@example.com"])
        self.assertEqual([c[0] for c in adapter.calls], ["555-0112"])

    def test_neither_opted_in_is_never_dispatched_but_counted(self):
        self._appointment(email_opt_in=False, sms_opt_in=False)
        adapter = FakeSmsAdapter()
        summary = send_due(self.window_start, self.window_end, adapter=adapter)
        self.assertEqual(summary.considered, 1)
        self.assertEqual(summary.dispatched, 0)
        self.assertEqual(summary.sent, 0)
        self.assertEqual(summary.skipped, 2)
        self.assertEqual(
            sorted(r.reason for r in summary.results),
            ["not_opted_in", "not_opted_in"],
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(adapter.calls, [])

    def test_missing_contact_details_skip_both_channels(self):
        self._appointment(email="", phone="")
        adapter = FakeSmsAdapter()
        summary = send_due(self.window_start, self.window_end, adapter=adapter)
        self.assertEqual(summary.dispatched, 0)
        self.assertEqual(summary.sent, 0)
        self.assertEqual(summary.skipped, 2)
        self.assertEqual(
            sorted(r.reason for r in summary.results),
            ["missing_email", "missing_phone"],
        )
        self.assertEqual(adapter.calls, [])

    def test_outside_window_and_cancelled_are_not_sent(self):
        self._appointment(start=self.window_end + timedelta(hours=1),
                          email="late@example.com")
        self._appointment(status=Appointment.Status.CANCELLED,
                          email="cancelled@example.com")
        adapter = FakeSmsAdapter()
        summary = send_due(self.window_start, self.window_end, adapter=adapter)
        self.assertEqual(summary.considered, 0)
        self.assertEqual(summary.sent, 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(adapter.calls, [])

    def test_precomputed_listing_is_used(self):
        self._appointment()
        listing = due_reminders(self.window_start, self.window_end)
        adapter = FakeSmsAdapter()
        summary = send_due(
            self.window_start, self.window_end, adapter=adapter, due=listing
        )
        self.assertEqual(summary.due, listing)
        self.assertEqual(summary.sent, 2)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(adapter.calls), 1)

    def test_explicit_appointments_still_gated_by_listing(self):
        appt = self._appointment(status=Appointment.Status.CANCELLED)
        adapter = FakeSmsAdapter()
        summary = send_due(
            self.window_start, self.window_end, adapter=adapter,
            appointments=[appt],
        )
        self.assertEqual(summary.considered, 1)
        self.assertEqual(summary.dispatched, 0)
        self.assertEqual(summary.sent, 0)
        self.assertEqual(summary.skipped, 2)
        self.assertEqual(adapter.calls, [])

    def test_reversed_window_raises(self):
        with self.assertRaises(ValueError):
            send_due(self.window_end, self.window_start,
                     adapter=FakeSmsAdapter())
