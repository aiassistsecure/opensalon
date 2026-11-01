"""Search the way the desk searches (Mark, 2026-10-31).

Clients: by first name, last name, first + last together, phone, or
email — in the booking sheet's search AND on the Clients page.
Services: searchable from the point of booking in the day book —
a type-to-search over the menu, not a dropdown to scroll.
"""
from django.test import Client, TestCase
from django.urls import reverse

from clients.models import Client as SalonClient
from saloncore.models import Salon, Service, ServiceCategory


class SearchPassTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.salon = Salon.objects.create(
            name="Mint", timezone="America/New_York"
        )
        self.krystal = SalonClient.objects.create(
            salon=self.salon,
            first_name="Krystal",
            last_name="Evans",
            phone="407-555-0100",
            email="krystal.evans@example.com",
        )
        SalonClient.objects.create(
            salon=self.salon,
            first_name="Jaime",
            last_name="Orta",
            phone="407-555-0142",
            email="jaime@example.net",
        )
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Colour"
        )
        Service.objects.create(
            category=category, name="Full Balayage", service_minutes=150
        )
        self.search_url = reverse("webui:daybook_client_search")
        self.clients_url = reverse("webui:clients")

    def booking_search(self, q):
        resp = self.client.get(self.search_url, {"q": q})
        return [c["name"] for c in resp.json()["clients"]]

    # -- the booking sheet's client search -------------------------------

    def test_booking_search_by_first_name(self):
        self.assertEqual(self.booking_search("Krystal"), ["Krystal Evans"])

    def test_booking_search_by_last_name(self):
        self.assertEqual(self.booking_search("Orta"), ["Jaime Orta"])

    def test_booking_search_by_first_and_last_together(self):
        self.assertEqual(
            self.booking_search("Krystal Evans"), ["Krystal Evans"]
        )

    def test_booking_search_by_email(self):
        self.assertEqual(
            self.booking_search("krystal.evans@example"),
            ["Krystal Evans"],
        )
        self.assertEqual(
            self.booking_search("example.net"), ["Jaime Orta"]
        )

    def test_booking_search_by_phone_digits(self):
        self.assertEqual(self.booking_search("5550100"), ["Krystal Evans"])

    def test_phone_search_reaches_past_the_area_code_funnel(self):
        # The measured failure on the real book: thousands of
        # phones share one area code, and the old search only
        # digit-compared the first few hundred substring
        # candidates alphabetically — 43% of real clients were
        # unreachable by their own number. Zed sorts last; his
        # number must still find him, and rank him first.
        for i in range(250):
            SalonClient.objects.create(
                salon=self.salon,
                first_name=f"Filler{i:03d}",
                last_name="Aardvark",
                phone=f"1407555{i:04d}",
            )
        SalonClient.objects.create(
            salon=self.salon,
            first_name="Zed",
            last_name="Zulu",
            phone="14075550999",
        )
        results = self.booking_search("4075550999")
        self.assertEqual(results[0], "Zed Zulu")

    def test_a_nameless_email_match_never_outranks_the_named_person(self):
        # The founder's own case: a record whose name fields are
        # empty (its email carries both tokens) ranked FIRST for
        # "Mark Evans", ahead of the man himself. A nameless
        # record is a last resort now; the named exact match leads.
        SalonClient.objects.create(
            salon=self.salon,
            first_name="Mark",
            last_name="Evans Sr",
            email="mark@fbojets.example",
        )
        SalonClient.objects.create(
            salon=self.salon,
            first_name="",
            last_name="",
            email="mark.evans@example.com",
        )
        results = self.booking_search("Mark Evans")
        self.assertEqual(results[0], "Mark Evans Sr")

    def test_full_name_ranks_first_past_a_common_surname(self):
        # Nine other Evanses sort ahead of Krystal by first name;
        # typing her full name must still put HER first — the exact
        # match is fetched and ranked ahead of the any-token rows.
        for first in (
            "Aly", "Amanda", "Charity", "Cole", "Collins",
            "Hope", "Jared", "June", "Kaitlyn",
        ):
            SalonClient.objects.create(
                salon=self.salon, first_name=first, last_name="Evans"
            )
        results = self.booking_search("Krystal Evans")
        self.assertEqual(results[0], "Krystal Evans")

    # -- the Clients page ---------------------------------------------------

    def test_clients_page_finds_first_and_last_together(self):
        html = self.client.get(
            self.clients_url, {"q": "Krystal Evans"}
        ).content.decode()
        self.assertIn("Krystal", html)
        self.assertIn("Evans", html)
        self.assertNotIn("Orta", html)

    def test_clients_page_finds_by_email(self):
        html = self.client.get(
            self.clients_url, {"q": "krystal.evans@example"}
        ).content.decode()
        self.assertIn("Krystal", html)
        self.assertNotIn("Orta", html)

    def test_clients_page_finds_by_phone_digits(self):
        html = self.client.get(
            self.clients_url, {"q": "5550100"}
        ).content.decode()
        self.assertIn("Krystal", html)
        self.assertNotIn("Orta", html)

    # -- services at the point of booking --------------------------------

    def test_booking_sheet_searches_services(self):
        html = self.client.get(reverse("webui:daybook")).content.decode()
        self.assertIn('id="bkServiceSearch"', html)
        self.assertIn('id="bkServiceResults"', html)
        self.assertNotIn('<select id="bkService">', html)

    def test_booking_options_carry_searchable_services(self):
        data = self.client.get(
            reverse("webui:daybook_book_options")
        ).json()
        self.assertEqual(len(data["services"]), 1)
        service = data["services"][0]
        self.assertEqual(service["name"], "Full Balayage")
        self.assertEqual(service["category"], "Colour")
        self.assertEqual(service["minutes"], 150)
