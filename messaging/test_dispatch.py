from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.adapters import SmsAdapter, SmsResult
from messaging.dispatch import ReminderDispatchSummary, send_due_reminders
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
class ReminderDispatchTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Haircuts")
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

    def test_both_opted_in_gets_both_channels(self):
        self._appointment(sms_opt_in=True, email_opt_in=True)
        adapter = FakeSmsAdapter()
        summary = send_due_reminders(now=self.now, adapter=adapter)
        self.assertIsInstance(summary, ReminderDispatchSummary)
        self.assertEqual(summary.email.sent, 1)
        self.assertEqual(summary.sms.sent, 1)
        self.assertEqual(summary.sent, 2)
        self.assertEqual(summary.skipped, 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["client@example.com"])
        self.assertEqual([c[0] for c in adapter.calls], ["555-0100"])

    def test_email_only_opt_in_gets_email_only(self):
        self._appointment(email_opt_in=True, sms_opt_in=False)
        adapter = FakeSmsAdapter()
        summary = send_due_reminders(now=self.now, adapter=adapter)
        self.assertEqual(summary.email.sent, 1)
        self.assertEqual(summary.sms.sent, 0)
        self.assertEqual(summary.sms.skipped_not_opted_in, 1)
        self.assertEqual(summary.sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(adapter.calls, [])

    def test_sms_only_opt_in_gets_sms_only(self):
        self._appointment(sms_opt_in=True, email_opt_in=False)
        adapter = FakeSmsAdapter()
        summary = send_due_reminders(now=self.now, adapter=adapter)
        self.assertEqual(summary.sms.sent, 1)
        self.assertEqual(summary.email.sent, 0)
        self.assertEqual(summary.email.skipped_not_opted_in, 1)
        self.assertEqual(summary.sent, 1)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual([c[0] for c in adapter.calls], ["555-0100"])

    def test_neither_opt_in_gets_nothing(self):
        self._appointment(sms_opt_in=False, email_opt_in=False)
        adapter = FakeSmsAdapter()
        summary = send_due_reminders(now=self.now, adapter=adapter)
        self.assertEqual(summary.sent, 0)
        self.assertEqual(summary.email.skipped_not_opted_in, 1)
        self.assertEqual(summary.sms.skipped_not_opted_in, 1)
        self.assertEqual(summary.skipped, 2)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(adapter.calls, [])

    def test_mixed_clients_each_get_only_their_channels(self):
        self._appointment(sms_opt_in=True, email_opt_in=True,
                          phone="555-0111", email="both@example.com")
        self._appointment(email_opt_in=True,
                          phone="555-0112", email="emailonly@example.com")
        self._appointment(sms_opt_in=True,
                          phone="555-0113", email="smsonly@example.com")
        self._appointment(phone="555-0114", email="neither@example.com")
        adapter = FakeSmsAdapter()
        summary = send_due_reminders(now=self.now, adapter=adapter)
        self.assertEqual(summary.email.sent, 2)
        self.assertEqual(summary.sms.sent, 2)
        self.assertEqual(summary.sent, 4)
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox),
            ["both@example.com", "emailonly@example.com"],
        )
        self.assertEqual(
            sorted(c[0] for c in adapter.calls), ["555-0111", "555-0113"]
        )
