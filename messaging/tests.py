from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.adapters import ConsoleSmsAdapter, SmsAdapter, SmsResult, get_sms_adapter
from messaging.reminders import (
    send_appointment_reminder,
    send_email_reminder,
    send_sms_reminder,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember


class FakeSmsAdapter(SmsAdapter):
    """Test double satisfying the adapter interface."""

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
class ReminderServiceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Haircuts")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        self.start = timezone.now() + timedelta(days=1)

    def _appointment(self, **client_kwargs):
        defaults = dict(
            salon=self.salon, first_name="Test", last_name="Example",
            phone="555-0100", email="client@example.com",
        )
        defaults.update(client_kwargs)
        client = Client.objects.create(**defaults)
        return Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            start=self.start, end=self.start + timedelta(minutes=45),
        )

    def test_adapter_interface_satisfied_by_test_double(self):
        adapter = FakeSmsAdapter()
        self.assertIsInstance(adapter, SmsAdapter)
        result = adapter.send_sms("555-0100", "hello")
        self.assertTrue(result.success)
        self.assertEqual(adapter.calls, [("555-0100", "hello")])
        with self.assertRaises(TypeError):
            SmsAdapter()

    def test_console_adapter_and_default_resolution(self):
        result = ConsoleSmsAdapter().send_sms("555-0100", "hello")
        self.assertTrue(result.success)
        self.assertIsInstance(get_sms_adapter(), ConsoleSmsAdapter)

    def test_opted_in_sms_sends_through_adapter(self):
        appt = self._appointment(sms_opt_in=True)
        adapter = FakeSmsAdapter()
        result = send_sms_reminder(appt, adapter=adapter)
        self.assertTrue(result.sent)
        self.assertEqual(result.reference, "fake-1")
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(adapter.calls[0][0], "555-0100")
        self.assertIn("Haircut", adapter.calls[0][1])

    def test_opted_out_sms_is_skipped_without_send(self):
        appt = self._appointment(sms_opt_in=False)
        adapter = FakeSmsAdapter()
        result = send_appointment_reminder(appt, "sms", adapter=adapter)
        self.assertFalse(result.sent)
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "not_opted_in")
        self.assertEqual(adapter.calls, [])

    def test_opted_in_email_sends_via_django_mail(self):
        appt = self._appointment(email_opt_in=True)
        result = send_email_reminder(appt)
        self.assertTrue(result.sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["client@example.com"])
        self.assertIn("Haircut", mail.outbox[0].body)

    def test_opted_out_email_is_skipped_without_send(self):
        appt = self._appointment(email_opt_in=False)
        result = send_appointment_reminder(appt, "email")
        self.assertFalse(result.sent)
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "not_opted_in")
        self.assertEqual(len(mail.outbox), 0)

    def test_opted_out_client_skipped_on_both_channels(self):
        appt = self._appointment(sms_opt_in=False, email_opt_in=False)
        adapter = FakeSmsAdapter()
        sms = send_appointment_reminder(appt, "sms", adapter=adapter)
        email = send_appointment_reminder(appt, "email")
        self.assertEqual((sms.status, email.status), ("skipped", "skipped"))
        self.assertEqual(adapter.calls, [])
        self.assertEqual(len(mail.outbox), 0)
