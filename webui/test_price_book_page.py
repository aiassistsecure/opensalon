"""The Price Book page: light theme, human column order."""
from django.test import Client, TestCase
from django.urls import reverse

from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    StaffLevel,
)


class PriceBookPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.salon = Salon.objects.create(
            name="Mint", timezone="America/New_York"
        )
        for name in (
            "H4zBPQ63XrW87rOtEvXClA",  # a raw id no repair has named
            "Artist Level 6",
            "Unassigned ····XClA",
            "Base",
        ):
            StaffLevel.objects.create(salon=self.salon, name=name)
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair"
        )
        Service.objects.create(
            category=category, name="Women's Haircut", service_minutes=60
        )
        self.url = reverse("webui:pricebook")

    def test_page_is_light_and_columns_read_like_the_salon_talks(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("page-light", html)
        # A level still named by a source id never prints the id:
        # ids are private keys, not public titles. It reads as an
        # Unassigned set carrying only its last four characters.
        self.assertNotIn("H4zBPQ63XrW87rOtEvXClA", html)
        order = [
            html.index(name)
            for name in (
                "Base",
                "Artist Level 6",
                "Unassigned ····XClA",
            )
        ]
        self.assertEqual(order, sorted(order))
