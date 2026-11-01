"""Public online booking — the salon-branded page.

Pins: the page offers only what the onlinebooking lane
offers (rostered time, online toggle on, long enough for the
service); the confirm path re-checks the slot at the write
and lands an origin="online" appointment through the lane's
own create; a taken slot refuses plainly; the client book is
matched silently by phone, never exposed.
"""
import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember


class BookingPageTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Brand Salon", timezone="UTC", currency="USD"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Cuts")
        self.service = Service.objects.create(
            category=category, name="Signature Cut", service_minutes=60
        )
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Dana Stylist"
        )
        self.hidden = StaffMember.objects.create(
            salon=self.salon, display_name="Off Toggle",
            online_bookable=False,
        )
        self.tomorrow = timezone.now().date() + datetime.timedelta(days=1)
        for member in (self.staff, self.hidden):
            RosterPattern.objects.create(
                staff_member=member, weekday=self.tomorrow.weekday(),
                start_time=datetime.time(9, 0),
                end_time=datetime.time(12, 0),
            )

    def book_url(self, **params):
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{reverse('webui:book')}?{query}"

    def test_menu_shows_services_under_the_salons_name(self):
        response = self.client.get(reverse("webui:book"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Brand Salon")
        self.assertContains(response, "Signature Cut")
        self.assertNotContains(response, "OpenSalon")

    def test_slots_come_from_the_roster_and_the_toggle(self):
        response = self.client.get(
            self.book_url(
                service=self.service.pk, day=self.tomorrow.isoformat()
            )
        )
        sections = response.context["sections"]
        names = [s["staff"].display_name for s in sections]
        self.assertEqual(names, ["Dana Stylist"])
        starts = sections[0]["starts"]
        self.assertTrue(starts)
        self.assertTrue(all(s.minute % 15 == 0 for s in starts))
        self.assertTrue(
            all(s.date() == self.tomorrow for s in starts)
        )

    def test_full_flow_books_an_online_appointment(self):
        page = self.client.get(
            self.book_url(
                service=self.service.pk, day=self.tomorrow.isoformat()
            )
        )
        start = page.context["sections"][0]["starts"][0]
        response = self.client.post(
            reverse("webui:book_confirm"),
            {
                "service": self.service.pk, "staff": self.staff.pk,
                "day": self.tomorrow.isoformat(),
                "time": start.strftime("%H:%M"),
                "first_name": "Robin", "last_name": "Guest",
                "phone": "555-0110", "email": "robin@example.com",
                "note": "First visit",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("webui:book_done"))
        appointment = Appointment.objects.get()
        self.assertEqual(appointment.origin, "online")
        self.assertEqual(appointment.service, self.service)
        self.assertEqual(appointment.client.phone, "555-0110")
        self.assertEqual(appointment.start, start)
        done = self.client.get(reverse("webui:book_done"))
        self.assertEqual(done.status_code, 200)
        self.assertContains(done, "Signature Cut")
        self.assertContains(done, "Robin")

    def test_returning_guest_matches_by_phone_silently(self):
        existing = Client.objects.create(
            salon=self.salon, first_name="Robin", last_name="Guest",
            phone="555-0110", email="old@example.com",
        )
        page = self.client.get(
            self.book_url(
                service=self.service.pk, day=self.tomorrow.isoformat()
            )
        )
        start = page.context["sections"][0]["starts"][0]
        self.client.post(
            reverse("webui:book_confirm"),
            {
                "service": self.service.pk, "staff": self.staff.pk,
                "day": self.tomorrow.isoformat(),
                "time": start.strftime("%H:%M"),
                "first_name": "Robin", "last_name": "Guest",
                "phone": "555-0110", "email": "new@example.com",
                "note": "",
            },
        )
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(Appointment.objects.get().client, existing)

    def test_taken_slot_and_toggle_off_both_refuse(self):
        page = self.client.get(
            self.book_url(
                service=self.service.pk, day=self.tomorrow.isoformat()
            )
        )
        start = page.context["sections"][0]["starts"][0]
        payload = {
            "service": self.service.pk, "staff": self.staff.pk,
            "day": self.tomorrow.isoformat(),
            "time": start.strftime("%H:%M"),
            "first_name": "Robin", "last_name": "Guest",
            "phone": "555-0110", "email": "", "note": "",
        }
        self.client.post(reverse("webui:book_confirm"), payload)
        self.assertEqual(Appointment.objects.count(), 1)
        payload["phone"] = "555-9999"
        response = self.client.post(reverse("webui:book_confirm"), payload)
        self.assertIn("taken=1", response.url)
        self.assertEqual(Appointment.objects.count(), 1)
        payload["staff"] = self.hidden.pk
        payload["phone"] = "555-8888"
        response = self.client.post(reverse("webui:book_confirm"), payload)
        self.assertIn("taken=1", response.url)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_done_without_a_booking_redirects(self):
        response = self.client.get(reverse("webui:book_done"))
        self.assertEqual(response.status_code, 302)

    def test_menu_carries_service_search(self):
        # A real menu runs near a hundred services: the guest
        # filters it in place. The search box, the per-row
        # match key, and the empty-result note all render with
        # the menu; the filtering itself is pinned below.
        response = self.client.get(reverse("webui:book"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="bookSearch"')
        self.assertContains(response, 'data-name="signature cut"')
        self.assertContains(response, 'id="bookNoMatch"')

    def test_search_filter_and_its_hidden_rule_are_pinned(self):
        from pathlib import Path

        root = Path(__file__).parent
        template = (root / "templates" / "webui" / "book.html").read_text()
        css = (root / "static" / "webui" / "webui.css").read_text()
        # Every token must match the row's name; rows hide via
        # the hidden attribute...
        self.assertIn("tokens.every", template)
        self.assertIn("row.hidden = !hit", template)
        # ...which only bites because the stylesheet says so —
        # .book-service is display:flex, which would otherwise
        # override the hidden attribute's own display:none.
        self.assertIn(".book-service[hidden]{display:none}", css)
