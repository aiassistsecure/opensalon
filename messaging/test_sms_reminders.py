from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.adapters import SmsAdapter, SmsResult
from messaging.sms_reminders import due_appointments, send_due_sms_reminders
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


class SmsReminderDeliveryTests(TestCase):
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

    def _appointment(self, start=None, status=Appointment.Status.BOOKED,
                     **client_kwargs):
        defaults = dict(
            salon=self.salon, first_name="Test", last_name="Example",
            phone="555-0100", email="client@example.com",
            sms_opt_in=True,
        )
        defaults.update(client_kwargs)
        client = Client.objects.create(**defaults)
        start = start or self.start
        return Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            start=start, end=start + timedelta(minutes=45), status=status,
        )

    def test_opted_in_due_appointment_is_sent_through_adapter(self):
        self._appointment()
        adapter = FakeSmsAdapter()
        summary = send_due_sms_reminders(now=self.now, adapter=adapter)
        self.assertEqual(summary.sent, 1)
        self.assertEqual(summary.skipped, 0)
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(adapter.calls[0][0], "555-0100")
        self.assertIn("Haircut", adapter.calls[0][1])

    def test_opted_out_client_gets_nothing(self):
        self._appointment(sms_opt_in=False)
        adapter = FakeSmsAdapter()
        summary = send_due_sms_reminders(now=self.now, adapter=adapter)
        self.assertEqual(summary.sent, 0)
        self.assertEqual(summary.skipped_not_opted_in, 1)
        self.assertEqual(adapter.calls, [])

    def test_email_opt_in_alone_does_not_enable_sms(self):
        self._appointment(sms_opt_in=False, email_opt_in=True)
        adapter = FakeSmsAdapter()
        summary = send_due_sms_reminders(now=self.now, adapter=adapter)
        self.assertEqual(summary.sent, 0)
        self.assertEqual(summary.skipped_not_opted_in, 1)
        self.assertEqual(adapter.calls, [])

    def test_missing_phone_is_skipped_without_send(self):
        self._appointment(phone="")
        adapter = FakeSmsAdapter()
        summary = send_due_sms_reminders(now=self.now, adapter=adapter)
        self.assertEqual(summary.sent, 0)
        self.assertEqual(summary.skipped_missing_phone, 1)
        self.assertEqual(adapter.calls, [])

    def test_confirmed_sends_but_cancelled_and_completed_do_not(self):
        self._appointment(status=Appointment.Status.CONFIRMED,
                          phone="555-0111")
        self._appointment(status=Appointment.Status.CANCELLED,
                          phone="555-0112")
        self._appointment(status=Appointment.Status.COMPLETED,
                          phone="555-0113")
        adapter = FakeSmsAdapter()
        summary = send_due_sms_reminders(
            now=self.now, appointments=Appointment.objects.all(),
            adapter=adapter,
        )
        self.assertEqual(summary.sent, 1)
        self.assertEqual(summary.skipped_status, 2)
        self.assertEqual([c[0] for c in adapter.calls], ["555-0111"])

    def test_due_window_excludes_past_and_far_future(self):
        self._appointment(start=self.now - timedelta(hours=1),
                          phone="555-0121")
        self._appointment(start=self.now + timedelta(days=3),
                          phone="555-0122")
        self._appointment(phone="555-0123")
        self.assertEqual(
            [a.client.phone for a in due_appointments(now=self.now)],
            ["555-0123"],
        )
        adapter = FakeSmsAdapter()
        summary = send_due_sms_reminders(now=self.now, adapter=adapter)
        self.assertEqual(summary.sent, 1)
        self.assertEqual([c[0] for c in adapter.calls], ["555-0123"])

    def test_adapter_failure_is_counted_not_raised(self):
        self._appointment()
        adapter = FakeSmsAdapter(success=False)
        summary = send_due_sms_reminders(now=self.now, adapter=adapter)
        self.assertEqual(summary.sent, 0)
        self.assertEqual(summary.skipped_send_failed, 1)
        self.assertEqual(summary.skipped, 1)

    def test_command_reports_counts_only_and_uses_configured_adapter(self):
        self._appointment()
        self._appointment(sms_opt_in=False, phone="555-0199")
        adapter = FakeSmsAdapter()
        out = StringIO()
        with mock.patch(
            "messaging.reminders.get_sms_adapter", return_value=adapter
        ):
            call_command("send_sms_reminders", "--hours", "24", stdout=out)
        self.assertEqual([c[0] for c in adapter.calls], ["555-0100"])
        text = out.getvalue()
        self.assertIn("1 sent", text)
        self.assertIn("1 not opted in", text)
        self.assertNotIn("555-0100", text)
        self.assertNotIn("555-0199", text)
