"""The capability modals on their two pages.

Price book door: each service names how many of the team
perform it, and its modal saves the list. Team door: each
stylist names their service count, and their modal saves
their set — or mirrors another stylist's. Both saves land as
StaffService rows; after that, rows rule.
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.capabilities import performs
from team.models import StaffMember, StaffService


class CapabilityPageTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Modal Salon", timezone="UTC")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color"
        )
        self.level_a = StaffLevel.objects.create(
            salon=self.salon, name="Level A"
        )
        self.level_b = StaffLevel.objects.create(
            salon=self.salon, name="Level B"
        )
        self.ana = StaffMember.objects.create(
            salon=self.salon, display_name="Ana Artist",
            staff_level=self.level_a,
        )
        self.bea = StaffMember.objects.create(
            salon=self.salon, display_name="Bea Artist",
            staff_level=self.level_b,
        )
        self.cut = Service.objects.create(
            category=self.category, name="Full Color", service_minutes=90
        )
        self.gloss = Service.objects.create(
            category=self.category, name="Gloss", service_minutes=30
        )
        ServicePrice.objects.create(
            service=self.cut, staff_level=self.level_a,
            amount=Decimal("80.00"),
        )

    def test_price_book_names_the_count_and_renders_the_modal(self):
        response = self.client.get(reverse("webui:pricebook"))
        self.assertEqual(response.status_code, 200)
        # Full Color derives to Ana alone: 1 of 2.
        self.assertContains(response, "1 of 2")
        self.assertContains(response, f'id="capSvc{self.cut.pk}"')
        self.assertContains(response, "Who performs Full Color?")

    def test_price_book_save_materialises_the_service_list(self):
        response = self.client.post(
            reverse("webui:pricebook"),
            {
                "action": "performers",
                "service": self.cut.pk,
                "performer": [self.bea.pk],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Full Color: 1 of the team")
        self.assertEqual(
            StaffService.objects.filter(service=self.cut).count(), 2
        )
        self.assertTrue(performs(self.bea, self.cut))
        self.assertFalse(performs(self.ana, self.cut))

    def test_team_page_names_counts_and_renders_the_modal(self):
        response = self.client.get(reverse("webui:team"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Services by stylist")
        self.assertContains(response, f'id="capMember{self.ana.pk}"')
        # Ana derives Full Color + the open Gloss: 2 services.
        self.assertContains(response, "2 services")

    def test_team_save_materialises_the_members_set(self):
        response = self.client.post(
            reverse("webui:team"),
            {
                "action": "services",
                "member": self.bea.pk,
                "service": [self.cut.pk],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bea Artist now performs 1 services.")
        self.assertTrue(performs(self.bea, self.cut))
        self.assertFalse(performs(self.bea, self.gloss))

    def test_team_copy_mirrors_another_stylist(self):
        response = self.client.post(
            reverse("webui:team"),
            {
                "action": "copy_services",
                "member": self.bea.pk,
                "source": self.ana.pk,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "services now mirror Ana Artist")
        self.assertTrue(performs(self.bea, self.cut))
        self.assertTrue(performs(self.bea, self.gloss))

    def test_modals_ride_the_app_modal_law(self):
        from pathlib import Path

        root = Path(__file__).parent
        js = (root / "static" / "webui" / "webui.js").read_text()
        # One delegated ear opens and closes them; the bulk
        # buttons tick a whole category group at once.
        self.assertIn('closest("[data-cap-open]")', js)
        self.assertIn('closest("[data-cap-close]")', js)
        self.assertIn("[data-cap-all],[data-cap-none]", js)
        for template_name in ("pricebook.html", "roster.html"):
            template = (
                root / "templates" / "webui" / template_name
            ).read_text()
            self.assertIn("book-modal hidden", template)
            self.assertIn("data-cap-open", template)
        # The collision law from PR #464: no unscoped booking
        # enclave rule crept back in with these styles.
        css = (root / "static" / "webui" / "webui.css").read_text()
        self.assertIn(".cap-list", css)
