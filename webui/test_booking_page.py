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

    def availability(self):
        response = self.client.get(reverse("webui:book_availability"))
        self.assertEqual(response.status_code, 200)
        return response.json()

    def first_start(self):
        """Tomorrow's first offered start, as an \"H:M\" string —
        the first start the page's own local sort produces from
        the resident picture: Dana's first free span opens on
        the quarter and the hour-long service fits inside it."""
        payload = self.availability()
        spans = payload["free"][self.tomorrow.isoformat()][
            str(self.staff.pk)
        ]
        return spans[0][0]

    def test_menu_shows_services_under_the_salons_name(self):
        response = self.client.get(reverse("webui:book"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Brand Salon")
        self.assertContains(response, "Signature Cut")
        self.assertNotContains(response, "OpenSalon")

    def test_availability_comes_from_the_roster_and_the_toggle(self):
        payload = self.availability()
        self.assertEqual(len(payload["days"]), 14)
        # The toggle-off stylist is not in the picture at all.
        self.assertEqual(
            payload["staff"], {str(self.staff.pk): "Dana Stylist"}
        )
        offered = payload["services"][str(self.service.pk)]
        self.assertEqual(offered["minutes"], 60)
        self.assertEqual(offered["staff"], [self.staff.pk])
        self.assertEqual(
            payload["free"][self.tomorrow.isoformat()][str(self.staff.pk)],
            [["09:00", "12:00"]],
        )

    def test_availability_subtracts_a_booked_span(self):
        guest = Client.objects.create(
            salon=self.salon, first_name="Early", last_name="Bird"
        )
        Appointment.objects.create(
            client=guest, staff_member=self.staff, service=self.service,
            start=datetime.datetime.combine(
                self.tomorrow, datetime.time(10, 0),
                tzinfo=datetime.timezone.utc,
            ),
            end=datetime.datetime.combine(
                self.tomorrow, datetime.time(11, 0),
                tzinfo=datetime.timezone.utc,
            ),
        )
        payload = self.availability()
        self.assertEqual(
            payload["free"][self.tomorrow.isoformat()][str(self.staff.pk)],
            [["09:00", "10:00"], ["11:00", "12:00"]],
        )

    def test_availability_respects_the_capability_matrix(self):
        # Priced for a level Dana doesn't hold: the price book's
        # derivation says she doesn't perform it, so the picture
        # offers the service with nobody until the salon enables
        # someone. The write path would refuse her too.
        from decimal import Decimal

        from saloncore.models import ServicePrice, StaffLevel

        level = StaffLevel.objects.create(salon=self.salon, name="Colorists")
        ServicePrice.objects.create(
            service=self.service, staff_level=level,
            amount=Decimal("50.00"),
        )
        payload = self.availability()
        self.assertEqual(
            payload["services"][str(self.service.pk)]["staff"], []
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

    def test_search_gathers_matches_and_restores_the_doors(self):
        from pathlib import Path

        root = Path(__file__).parent
        template = (root / "templates" / "webui" / "book.html").read_text()
        # Every token must match the row's name; matches are
        # gathered into the lobby's results area (the buttons
        # move — one button, one truth, wherever it stands),
        # and clearing the box rehomes them behind the doors.
        self.assertIn("tokens.every", template)
        self.assertIn("results.appendChild(row)", template)
        self.assertIn("function rehome()", template)
        self.assertIn('id="searchResults"', template)

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
            'id="roomMenu"', 'id="roomCategory"', 'id="roomTimes"',
            'id="roomDetails"', 'id="roomDone"', 'id="bookToasts"',
            'id="catDoors"', 'id="serviceBank"',
        ):
            self.assertContains(response, marker)
        template = (
            Path(__file__).parent / "templates" / "webui" / "book.html"
        ).read_text()
        # Navigation is the edge table: named edges, traversed
        # by go(), over rooms shown and hidden in place.
        self.assertIn("EDGES", template)
        self.assertIn("function go(edge)", template)
        self.assertIn("pickCategory", template)
        self.assertIn("pickService", template)
        self.assertIn("booked", template)
        self.assertIn("function toast(", template)

    def test_lobby_shows_category_doors_not_the_whole_menu(self):
        # The first layer is doors and a search box: each
        # category renders as one door carrying its service
        # count, and the service buttons themselves wait in
        # the bank for a room to borrow them.
        response = self.client.get(reverse("webui:book"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "book-catdoor")
        self.assertContains(response, 'data-cat="0"')
        self.assertContains(response, "1 service")
        self.assertContains(response, 'id="catServices"')

    def test_times_sort_locally_from_the_resident_picture(self):
        # The founder's law (2026-11-02): availability loads
        # when the guest arrives, resident in the page, and a
        # service pick sorts it locally by service and
        # duration. The per-pick slot fetch was the ten-second
        # "Finding open times…" stall — and its race was the
        # stale-name bug before that: a slow response for the
        # previous pick repainting the new pick's room. A
        # computation can't land late. The heading still names
        # the tapped pick at once.
        from pathlib import Path

        response = self.client.get(reverse("webui:book"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="bookAvailability"')
        template = (
            Path(__file__).parent / "templates" / "webui" / "book.html"
        ).read_text()
        self.assertIn("function computeSlots(", template)
        self.assertIn("AVAIL.free", template)
        self.assertIn("cursor + svc.minutes <= end", template)
        self.assertIn("function refreshAvailability(", template)
        self.assertNotIn("book_slots", template)
        self.assertNotIn("SLOTS_URL", template)
        self.assertIn(
            'room("timesService").textContent = nameEl.textContent',
            template,
        )

    def test_second_confirm_for_own_booking_answers_already(self):
        # The founder's report (2026-11-02): he booked, and the
        # page answered "That time was just taken" and threw
        # him back to the slots — the slot was taken by his
        # own first confirm (a double tap, a retry after a
        # slow answer). Already-theirs is not a refusal: the
        # second answer names the standing booking, and no
        # second appointment is made.
        payload = {
            "service": self.service.pk, "staff": self.staff.pk,
            "day": self.tomorrow.isoformat(),
            "time": self.first_start(),
            "first_name": "Robin", "last_name": "Guest",
            "phone": "555-0110", "email": "", "note": "",
            "format": "json",
        }
        first = self.client.post(reverse("webui:book_confirm"), payload)
        self.assertTrue(first.json()["ok"])
        self.assertEqual(Appointment.objects.count(), 1)
        second = self.client.post(reverse("webui:book_confirm"), payload)
        body = second.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["already"])
        self.assertEqual(body["summary"]["service"], "Signature Cut")
        self.assertEqual(Appointment.objects.count(), 1)

    def test_confirm_submit_is_structurally_single_flight(self):
        from pathlib import Path

        template = (
            Path(__file__).parent / "templates" / "webui" / "book.html"
        ).read_text()
        # The double-tap race dies at the form, not just at a
        # disabled button; an "already" answer lands in the
        # done room like any success.
        self.assertIn("form.dataset.busy", template)
        self.assertIn("body.already", template)

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
