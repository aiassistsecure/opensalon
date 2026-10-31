from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.due import (
    appointments_due_between,
    channel_eligibility,
    due_reminders,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="salon@example.com",
)
class DueReminderListingTests(TestCase):
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

    def test_window_includes_edges_and_excludes_outside_ordered(self):
        early = self._appointment(start=self.window_start, email="a@example.com")
        late = self._appointment(start=self.window_end, email="b@example.com")
        self._appointment(
            start=self.window_start - timedelta(minutes=1), email="c@example.com"
        )
        self._appointment(
            start=self.window_end + timedelta(minutes=1), email="d@example.com"
        )
        self.assertEqual(
            list(appointments_due_between(self.window_start, self.window_end)),
            [early, late],
        )
        self.assertEqual(
            [d.appointment for d in due_reminders(self.window_start, self.window_end)],
            [early, late],
        )

    def test_reversed_window_raises(self):
        with self.assertRaises(ValueError):
            appointments_due_between(self.window_end, self.window_start)
        with self.assertRaises(ValueError):
            due_reminders(self.window_end, self.window_start)

    def test_both_channels_eligible(self):
        self._appointment()
        (due,) = due_reminders(self.window_start, self.window_end)
        self.assertTrue(due.email.eligible)
        self.assertTrue(due.sms.eligible)
        self.assertEqual(due.email.reason, "")
        self.assertEqual(due.eligible_channels, ("email", "sms"))
        self.assertTrue(due.any_eligible)

    def test_channels_are_independent(self):
        self._appointment(email_opt_in=True, sms_opt_in=False, email="e@example.com")
        self._appointment(email_opt_in=False, sms_opt_in=True, email="s@example.com")
        self._appointment(email_opt_in=False, sms_opt_in=False, email="n@example.com")
        dues = due_reminders(self.window_start, self.window_end)
        self.assertEqual(
            [d.eligible_channels for d in dues], [("email",), ("sms",), ()]
        )
        self.assertEqual(dues[0].sms.reason, "not_opted_in")
        self.assertEqual(dues[1].email.reason, "not_opted_in")
        self.assertFalse(dues[2].any_eligible)

    def test_missing_contact_detail_per_channel(self):
        self._appointment(email="", phone="")
        (due,) = due_reminders(self.window_start, self.window_end)
        self.assertEqual(due.email.reason, "missing_email")
        self.assertEqual(due.sms.reason, "missing_phone")
        self.assertFalse(due.any_eligible)

    def test_non_remindable_status_ineligible_on_both_channels(self):
        appt = self._appointment(status=Appointment.Status.CANCELLED)
        # Explicit iterable surfaces the status gate, like the batch senders.
        (due,) = due_reminders(
            self.window_start, self.window_end,
            appointments=Appointment.objects.all(),
        )
        self.assertEqual(due.appointment, appt)
        self.assertEqual(due.email.reason, "not_remindable_status")
        self.assertEqual(due.sms.reason, "not_remindable_status")
        # And the default queryset excludes it entirely.
        self.assertEqual(due_reminders(self.window_start, self.window_end), [])

    def test_channel_eligibility_rejects_unknown_channel(self):
        appt = self._appointment()
        with self.assertRaises(ValueError):
            channel_eligibility(appt, "pigeon")
        (due,) = due_reminders(self.window_start, self.window_end)
        with self.assertRaises(ValueError):
            due.eligibility("pigeon")

    def test_listing_sends_nothing(self):
        self._appointment()
        due_reminders(self.window_start, self.window_end)
        self.assertEqual(len(mail.outbox), 0)
