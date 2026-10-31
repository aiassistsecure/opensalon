"""Automations page — reminders wired to the real backend.

Pins: the due list is the messaging lane's own eligibility law
over the next 48 hours, scoped to this salon; the send button
runs the lane's send-due over exactly the displayed listing;
only real sends land in the log; the channels card tells the
truth about what's configured (console SMS = rehearsed, not
delivered).
"""
import datetime

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.models import ReminderSend
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember


class AutomationsPageTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Auto Salon", timezone="UTC", currency="USD"
        )
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Dana Stylist"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Cuts")
        self.service = Service.objects.create(
            category=category, name="Signature Cut", service_minutes=60
        )
        self.now = timezone.now()

        def guest(first, **kwargs):
            return Client.objects.create(
                salon=self.salon, first_name=first, last_name="Guest",
                **kwargs,
            )

        self.reachable = guest(
            "Robin", email="robin@example.com", phone="555-0110",
            email_opt_in=True, sms_opt_in=True,
        )
        self.opted_out = guest(
            "Pat", email="pat@example.com", phone="555-0111",
            email_opt_in=False, sms_opt_in=False,
        )

        def book(client, when, status="booked"):
            return Appointment.objects.create(
                client=client, staff_member=self.staff,
                service=self.service, start=when,
                end=when + datetime.timedelta(hours=1), status=status,
            )

        self.due_a = book(self.reachable, self.now + datetime.timedelta(hours=24))
        self.due_b = book(self.opted_out, self.now + datetime.timedelta(hours=25))
        book(self.reachable, self.now - datetime.timedelta(hours=2))
        book(self.reachable, self.now + datetime.timedelta(hours=72))
        book(self.reachable, self.now + datetime.timedelta(hours=26),
             status="cancelled")

    def test_due_list_is_the_next_48_hours_with_eligibility(self):
        response = self.client.get(reverse("webui:automations"))
        self.assertEqual(response.status_code, 200)
        due = response.context["due"]
        ids = [d.appointment.pk for d in due]
        self.assertEqual(ids, [self.due_a.pk, self.due_b.pk])
        by_id = {d.appointment.pk: d for d in due}
        self.assertTrue(by_id[self.due_a.pk].email.eligible)
        self.assertTrue(by_id[self.due_a.pk].sms.eligible)
        self.assertFalse(by_id[self.due_b.pk].email.eligible)
        self.assertTrue(by_id[self.due_b.pk].email.reason)
        self.assertEqual(response.context["email_ready"], 1)
        self.assertEqual(response.context["sms_ready"], 1)

    def test_channels_card_tells_the_truth(self):
        response = self.client.get(reverse("webui:automations"))
        self.assertEqual(response.context["sms_adapter"], "ConsoleSmsAdapter")
        self.assertTrue(response.context["sms_console"])
        self.assertContains(response, "rehearsed, not delivered")

    def test_send_button_runs_the_backend(self):
        response = self.client.post(reverse("webui:automations_send"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("sent=", response.url)
        sends = ReminderSend.objects.all()
        self.assertTrue(
            sends.filter(appointment=self.due_a, channel="email").exists()
        )
        self.assertFalse(sends.filter(appointment=self.due_b).exists())
        self.assertEqual(len(mail.outbox), 1)

    def test_sent_notice_parses_counts(self):
        response = self.client.get(
            reverse("webui:automations"), {"sent": "3", "skipped": "1"}
        )
        self.assertEqual(
            response.context["sent_notice"], {"sent": 3, "skipped": 1}
        )
        response = self.client.get(
            reverse("webui:automations"), {"sent": "abc", "skipped": "1"}
        )
        self.assertIsNone(response.context["sent_notice"])

    def test_send_is_post_only(self):
        response = self.client.get(reverse("webui:automations_send"))
        self.assertEqual(response.status_code, 405)
