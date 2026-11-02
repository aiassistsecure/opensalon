"""My Day: the stylist's own book, behind their account.

Signed-out visitors bounce to sign-in. Signed in, a stylist
sees only their own appointments, their arrival pings show
exactly once (the showing stamps them seen), and Start
service moves their own checked-in guest into service —
never anyone else's.
"""

import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember, StaffNotification


class MyDayTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="My Day Salon", timezone="UTC")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Cut", service_minutes=60
        )
        self.dana = StaffMember.objects.create(
            salon=self.salon, display_name="Dana",
            email="dana@salon.test", pin="1234",
        )
        self.bea = StaffMember.objects.create(
            salon=self.salon, display_name="Bea",
            email="bea@salon.test", pin="5678",
        )
        today = timezone.now().date()
        start = timezone.make_aware(
            datetime.datetime.combine(today, datetime.time(15, 0))
        )
        mine = Client.objects.create(
            salon=self.salon, first_name="Mina", last_name="Mine"
        )
        hers = Client.objects.create(
            salon=self.salon, first_name="Hana", last_name="Hers"
        )
        self.my_appt = Appointment.objects.create(
            client=mine, staff_member=self.dana, service=self.service,
            service_name="Cut", start=start,
            end=start + datetime.timedelta(hours=1),
            status=Appointment.Status.ARRIVED,
        )
        self.her_appt = Appointment.objects.create(
            client=hers, staff_member=self.bea, service=self.service,
            service_name="Cut", start=start,
            end=start + datetime.timedelta(hours=1),
            status=Appointment.Status.ARRIVED,
        )

    def sign_in_as(self, member):
        session = self.client.session
        session["staff_member_id"] = member.pk
        session.save()

    def test_signed_out_redirects_to_sign_in(self):
        response = self.client.get(reverse("webui:my_day"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("webui:sign_in"))

    def test_only_my_appointments_appear(self):
        self.sign_in_as(self.dana)
        response = self.client.get(reverse("webui:my_day"))
        self.assertContains(response, "Mina Mine")
        self.assertNotContains(response, "Hana Hers")

    def test_arrival_shows_once_and_is_marked_seen(self):
        note = StaffNotification.objects.create(
            staff_member=self.dana, appointment=self.my_appt, kind="arrived"
        )
        self.sign_in_as(self.dana)
        response = self.client.get(reverse("webui:my_day"))
        self.assertContains(response, "Mina Mine is here")
        note.refresh_from_db()
        self.assertIsNotNone(note.seen_at)
        response = self.client.get(reverse("webui:my_day"))
        self.assertNotContains(response, "is here")

    def test_start_service_moves_my_guest(self):
        self.sign_in_as(self.dana)
        response = self.client.post(
            reverse("webui:my_day"),
            {"action": "start", "appointment": self.my_appt.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.my_appt.refresh_from_db()
        self.assertEqual(self.my_appt.status, Appointment.Status.IN_SERVICE)

    def test_start_service_never_touches_another_stylists_guest(self):
        self.sign_in_as(self.dana)
        self.client.post(
            reverse("webui:my_day"),
            {"action": "start", "appointment": self.her_appt.pk},
        )
        self.her_appt.refresh_from_db()
        self.assertEqual(self.her_appt.status, Appointment.Status.ARRIVED)
