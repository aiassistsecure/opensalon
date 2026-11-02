"""Arrival pings: check-in tells the stylist's account.

The founder's flow (2026-11-02): the desk checks a guest in,
the stylist's account is told their client has arrived, then
the stylist begins the service. The ping is born in the one
status machinery every door shares (`_do_status`), exactly
once per arrival — starting the service, undoing nothing,
and no-shows stay silent.
"""

import datetime

from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember, StaffNotification
from webui.views import _do_status


class ArrivalNotificationTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Ping Salon", timezone="UTC")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Cut", service_minutes=60
        )
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Dana"
        )
        client = Client.objects.create(
            salon=self.salon, first_name="Robin", last_name="Guest"
        )
        start = timezone.now().replace(hour=10, minute=0, second=0,
                                       microsecond=0)
        self.appt = Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            service_name="Cut", start=start,
            end=start + datetime.timedelta(hours=1),
        )

    def test_checkin_creates_one_notification(self):
        self.assertIsNone(
            _do_status(self.appt, Appointment.Status.ARRIVED)
        )
        notes = StaffNotification.objects.filter(staff_member=self.staff)
        self.assertEqual(notes.count(), 1)
        note = notes.get()
        self.assertEqual(note.appointment, self.appt)
        self.assertEqual(note.kind, "arrived")
        self.assertIsNone(note.seen_at)

    def test_starting_the_service_creates_none(self):
        _do_status(self.appt, Appointment.Status.ARRIVED)
        self.appt.refresh_from_db()
        _do_status(self.appt, Appointment.Status.IN_SERVICE)
        self.assertEqual(StaffNotification.objects.count(), 1)

    def test_undo_and_recheckin_pings_again(self):
        _do_status(self.appt, Appointment.Status.ARRIVED)
        self.appt.refresh_from_db()
        _do_status(self.appt, Appointment.Status.BOOKED)
        self.appt.refresh_from_db()
        _do_status(self.appt, Appointment.Status.ARRIVED)
        self.assertEqual(StaffNotification.objects.count(), 2)

    def test_no_show_creates_none(self):
        _do_status(self.appt, Appointment.Status.NO_SHOW)
        self.assertEqual(StaffNotification.objects.count(), 0)
