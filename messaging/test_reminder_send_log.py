from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.adapters import SmsAdapter, SmsResult
from messaging.dispatch import send_due_reminders
from messaging.models import ReminderSend
from messaging.send_due import send_due
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
class ReminderSendLogTests(TestCase):
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

    def test_dispatch_logs_one_row_per_successful_channel(self):
        appt = self._appointment(sms_opt_in=True, email_opt_in=True)
        summary = send_due_reminders(now=self.now, adapter=FakeSmsAdapter())
        self.assertEqual(summary.sent, 2)
        rows = list(ReminderSend.objects.order_by("channel"))
        self.assertEqual(len(rows), 2)
        self.assertEqual([r.channel for r in rows], ["email", "sms"])
        for row in rows:
            self.assertEqual(row.appointment, appt)
            self.assertEqual(row.client, appt.client)
            self.assertEqual(row.status, ReminderSend.Status.SENT)
            self.assertIsNotNone(row.sent_at)
        self.assertEqual(rows[0].detail, "")
        self.assertEqual(rows[1].detail, "fake-1")

    def test_opted_out_channels_log_nothing(self):
        self._appointment(sms_opt_in=False, email_opt_in=False)
        summary = send_due_reminders(now=self.now, adapter=FakeSmsAdapter())
        self.assertEqual(summary.sent, 0)
        self.assertEqual(ReminderSend.objects.count(), 0)

    def test_failed_sms_logs_nothing_but_email_still_logs(self):
        self._appointment(sms_opt_in=True, email_opt_in=True)
        summary = send_due_reminders(
            now=self.now, adapter=FakeSmsAdapter(success=False)
        )
        self.assertEqual(summary.sent, 1)
        rows = list(ReminderSend.objects.all())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].channel, "email")

    def test_send_due_path_logs_successful_dispatch(self):
        appt = self._appointment(sms_opt_in=True, email_opt_in=True)
        summary = send_due(
            self.now, self.now + timedelta(hours=24),
            adapter=FakeSmsAdapter(),
        )
        self.assertEqual(summary.sent, 2)
        self.assertEqual(
            ReminderSend.objects.filter(appointment=appt).count(), 2
        )
        self.assertEqual(len(mail.outbox), 1)

    def test_record_helper_stores_int_ids_via_fks(self):
        appt = self._appointment(email_opt_in=True)
        row = ReminderSend.record(appt, channel="email")
        self.assertEqual(row.appointment_id, appt.id)
        self.assertEqual(row.client_id, appt.client_id)
        self.assertEqual(row.status, "sent")
