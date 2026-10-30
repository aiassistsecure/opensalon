from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.email_reminders import (
    build_email_message,
    due_appointments,
    send_due_email_reminders,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="salon@example.com",
)
class EmailReminderDeliveryTests(TestCase):
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
            email_opt_in=True,
        )
        defaults.update(client_kwargs)
        client = Client.objects.create(**defaults)
        start = start or self.start
        return Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            start=start, end=start + timedelta(minutes=45), status=status,
        )

    def test_opted_in_due_appointment_is_emailed_via_locmem(self):
        self._appointment()
        summary = send_due_email_reminders(now=self.now)
        self.assertEqual(summary.sent, 1)
        self.assertEqual(summary.skipped, 0)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["client@example.com"])
        self.assertEqual(message.from_email, "salon@example.com")
        self.assertIn("Haircut", message.body)

    def test_opted_out_client_gets_nothing(self):
        self._appointment(email_opt_in=False)
        summary = send_due_email_reminders(now=self.now)
        self.assertEqual(summary.sent, 0)
        self.assertEqual(summary.skipped_not_opted_in, 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_sms_opt_in_alone_does_not_enable_email(self):
        self._appointment(email_opt_in=False, sms_opt_in=True)
        summary = send_due_email_reminders(now=self.now)
        self.assertEqual(summary.sent, 0)
        self.assertEqual(summary.skipped_not_opted_in, 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_email_is_skipped_without_send(self):
        self._appointment(email="")
        summary = send_due_email_reminders(now=self.now)
        self.assertEqual(summary.sent, 0)
        self.assertEqual(summary.skipped_missing_email, 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_confirmed_sends_but_cancelled_and_completed_do_not(self):
        self._appointment(status=Appointment.Status.CONFIRMED,
                          email="confirmed@example.com")
        self._appointment(status=Appointment.Status.CANCELLED,
                          email="cancelled@example.com")
        self._appointment(status=Appointment.Status.COMPLETED,
                          email="completed@example.com")
        # Explicit iterable: status gate must hold off the due queryset too.
        summary = send_due_email_reminders(
            now=self.now, appointments=Appointment.objects.all()
        )
        self.assertEqual(summary.sent, 1)
        self.assertEqual(summary.skipped_status, 2)
        self.assertEqual([m.to for m in mail.outbox],
                         [["confirmed@example.com"]])

    def test_due_window_excludes_past_and_far_future(self):
        self._appointment(start=self.now - timedelta(hours=1),
                          email="past@example.com")
        self._appointment(start=self.now + timedelta(days=3),
                          email="far@example.com")
        self._appointment(email="due@example.com")
        self.assertEqual(
            [a.client.email for a in due_appointments(now=self.now)],
            ["due@example.com"],
        )
        summary = send_due_email_reminders(now=self.now)
        self.assertEqual(summary.sent, 1)
        self.assertEqual([m.to for m in mail.outbox], [["due@example.com"]])

    def test_build_email_message_uses_default_from(self):
        appt = self._appointment()
        message = build_email_message(appt)
        self.assertEqual(message.from_email, "salon@example.com")
        self.assertEqual(message.to, ["client@example.com"])
        self.assertIn("Stylist One", message.body)

    def test_command_delivers_and_reports_counts_only(self):
        self._appointment()
        self._appointment(email_opt_in=False, email="optedout@example.com")
        out = StringIO()
        call_command("send_email_reminders", "--hours", "24", stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["client@example.com"])
        text = out.getvalue()
        self.assertIn("1 sent", text)
        self.assertIn("1 not opted in", text)
        self.assertNotIn("optedout@example.com", text)
        self.assertNotIn("client@example.com", text)
