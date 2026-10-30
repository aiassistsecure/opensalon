import json
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


class PriceFeedTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint On The Avenue")
        self.color = ServiceCategory.objects.create(
            name="Color", salon=self.salon, sort_order=1
        )
        self.cuts = ServiceCategory.objects.create(
            name="Haircuts", salon=self.salon, sort_order=2
        )
        self.level = StaffLevel.objects.create(
            name="Level 6", salon=self.salon, sort_order=1
        )
        self.junior = StaffLevel.objects.create(
            name="Junior", salon=self.salon, sort_order=2
        )
        self.service = Service.objects.create(
            name="Single Process Color", category=self.color, service_minutes=45
        )
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"),
        )
        ServicePrice.objects.create(
            service=self.service, staff_level=self.junior,
            amount=Decimal("65.00"), is_from=True,
        )
        self.url = reverse("saloncore:price-feed")

    def test_200_json_without_auth(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/json")
        data = json.loads(resp.content)
        self.assertIn("categories", data)

    def test_grouping_shape_and_prices_by_level(self):
        data = json.loads(self.client.get(self.url).content)
        self.assertEqual([c["name"] for c in data["categories"]], ["Color"])
        svc = data["categories"][0]["services"][0]
        self.assertEqual(svc["name"], "Single Process Color")
        self.assertEqual(svc["total_minutes"], 45)
        self.assertEqual(
            svc["prices"],
            [
                {"staff_level": "Level 6", "amount": "85.00", "is_from": False},
                {"staff_level": "Junior", "amount": "65.00", "is_from": True},
            ],
        )

    def test_inactive_price_excluded(self):
        ServicePrice.objects.filter(staff_level=self.junior).update(active=False)
        data = json.loads(self.client.get(self.url).content)
        prices = data["categories"][0]["services"][0]["prices"]
        self.assertEqual([p["staff_level"] for p in prices], ["Level 6"])

    def test_inactive_service_category_and_level_excluded(self):
        # Inactive service: its category should vanish if it was the only one.
        cut = Service.objects.create(
            name="Haircut", category=self.cuts, service_minutes=60
        )
        ServicePrice.objects.create(
            service=cut, staff_level=self.level, amount=Decimal("50.00")
        )
        cut.active = False
        cut.save()
        # Inactive category hides its services.
        hidden = ServiceCategory.objects.create(
            name="Hidden", salon=self.salon, active=False
        )
        ghost = Service.objects.create(
            name="Ghost", category=hidden, service_minutes=10
        )
        ServicePrice.objects.create(
            service=ghost, staff_level=self.level, amount=Decimal("1.00")
        )
        # Inactive staff level hides only that level's prices.
        self.junior.active = False
        self.junior.save()
        data = json.loads(self.client.get(self.url).content)
        self.assertEqual([c["name"] for c in data["categories"]], ["Color"])
        prices = data["categories"][0]["services"][0]["prices"]
        self.assertEqual([p["staff_level"] for p in prices], ["Level 6"])

    def test_get_only(self):
        for method in ("post", "put", "patch", "delete"):
            resp = getattr(self.client, method)(self.url)
            self.assertEqual(resp.status_code, 405, method)
