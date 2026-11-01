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

    def slots(self):
        response = self.client.get(
            reverse("webui:book_slots"), {"service": self.service.pk}
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def first_start(self):
        """Tomorrow's first offered start, as an \"H:M\" string —
        read from the enclave's data edge, the way the page does."""
        payload = self.slots()
        for day in payload["days"]:
            if day["date"] == self.tomorrow.isoformat():
                return day["sections"][0]["starts"][0]["t"]
        raise AssertionError("no starts offered tomorrow")

    def test_menu_shows_services_under_the_salons_name(self):
        response = self.client.get(reverse("webui:book"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Brand Salon")
        self.assertContains(response, "Signature Cut")
        self.assertNotContains(response, "OpenSalon")

    def test_slots_come_from_the_roster_and_the_toggle(self):
        payload = self.slots()
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["days"]), 14)
        tomorrow = next(
            d for d in payload["days"]
            if d["date"] == self.tomorrow.isoformat()
        )
        names = [s["staff"] for s in tomorrow["sections"]]
        self.assertEqual(names, ["Dana Stylist"])
        starts = tomorrow["sections"][0]["starts"]
        self.assertTrue(starts)
        self.assertTrue(
            all(int(s["t"].split(":")[1]) % 15 == 0 for s in starts)
        )

    def test_full_flow_books_an_online_appointment(self):
        start = self.first_start()
        response = self.client.post(
            reverse("webui:book_confirm"),
            {
                "service": self.service.pk, "staff": self.staff.pk,
                "day": self.tomorrow.isoformat(),
                "time": start,
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
        hour, minute = (int(p) for p in start.split(":"))
        self.assertEqual(
            (appointment.start.hour, appointment.start.minute), (hour, minute)
        )
        done = self.client.get(reverse("webui:book_done"))
        self.assertEqual(done.status_code, 200)
        self.assertContains(done, "Signature Cut")
        self.assertContains(done, "Robin")

    def test_returning_guest_matches_by_phone_silently(self):
        existing = Client.objects.create(
            salon=self.salon, first_name="Robin", last_name="Guest",
            phone="555-0110", email="old@example.com",
        )
        start = self.first_start()
        self.client.post(
            reverse("webui:book_confirm"),
            {
                "service": self.service.pk, "staff": self.staff.pk,
                "day": self.tomorrow.isoformat(),
                "time": start,
                "first_name": "Robin", "last_name": "Guest",
                "phone": "555-0110", "email": "new@example.com",
                "note": "",
            },
        )
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(Appointment.objects.get().client, existing)

    def test_taken_slot_and_toggle_off_both_refuse(self):
        start = self.first_start()
        payload = {
            "service": self.service.pk, "staff": self.staff.pk,
            "day": self.tomorrow.isoformat(),
            "time": start,
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

    def test_menu_groups_services_by_category(self):
        from saloncore.models import Service, ServiceCategory

        spa = ServiceCategory.objects.create(
            salon=self.salon, name="Rituals", sort_order=5
        )
        Service.objects.create(
            category=spa, name="Aveda Ritual", active=True,
            service_minutes=30,
        )
        response = self.client.get(reverse("webui:book"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "book-cat")
        self.assertContains(response, "Cuts")
        self.assertContains(response, "Rituals")
        self.assertContains(response, "Aveda Ritual")
        # The group data rides in the view's own context, in
        # the book's category order.
        groups = response.context["groups"]
        self.assertEqual([g["name"] for g in groups], ["Cuts", "Rituals"])

    def test_page_is_an_enclave_of_rooms_on_an_edge_table(self):
        from pathlib import Path

        response = self.client.get(reverse("webui:book"))
        self.assertEqual(response.status_code, 200)
        # Every step of the journey is a room already on the
        # page; the toast stack stands ready; a confirm bounce
        # can resume at the times room.
        for marker in (
            'id="roomMenu"', 'id="roomTimes"', 'id="roomDetails"',
            'id="roomDone"', 'id="bookToasts"',
        ):
            self.assertContains(response, marker)
        template = (
            Path(__file__).parent / "templates" / "webui" / "book.html"
        ).read_text()
        # Navigation is the edge table: named edges, traversed
        # by go(), over rooms shown and hidden in place.
        self.assertIn("EDGES", template)
        self.assertIn("function go(edge)", template)
        self.assertIn("pickService", template)
        self.assertIn("booked", template)
        self.assertIn("function toast(", template)

    def test_confirm_json_mode_answers_instead_of_redirecting(self):
        payload = {
            "service": self.service.pk, "staff": self.staff.pk,
            "day": self.tomorrow.isoformat(),
            "time": self.first_start(),
            "first_name": "Robin", "last_name": "Guest",
            "phone": "555-0110", "email": "", "note": "",
            "format": "json",
        }
        response = self.client.post(reverse("webui:book_confirm"), payload)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["summary"]["service"], "Signature Cut")
        self.assertEqual(body["summary"]["staff"], "Dana Stylist")
        self.assertEqual(Appointment.objects.count(), 1)
        # The same slot again: a spoken refusal the page can
        # toast, not a silent redirect to nowhere.
        payload["phone"] = "555-9999"
        response = self.client.post(reverse("webui:book_confirm"), payload)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "taken")
        self.assertTrue(body["message"])
        self.assertEqual(Appointment.objects.count(), 1)
