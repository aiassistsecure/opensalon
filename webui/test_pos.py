"""POS: the till's home — today's tenders, sales, and Cashup.

The page reads the checkout lane's own law (compute_tender_totals /
run_cashup). A cashup is a snapshot, not a lock: it can be run
repeatedly in a day and never blocks later sales.
"""
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from checkout.models import Cashup, Payment, Sale, SaleItem
from clients.models import Client as SalonClient
from saloncore.models import Salon


class PosPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.salon = Salon.objects.create(name="Mint", timezone="America/New_York")
        self.url = reverse("webui:pos")
        guest = SalonClient.objects.create(salon=self.salon, first_name="Krystal")
        self.sale = Sale.objects.create(
            salon=self.salon, client=guest, status=Sale.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        SaleItem.objects.create(
            sale=self.sale, kind=SaleItem.Kind.SERVICE,
            description="Women's Haircut", quantity=1,
            unit_price=Decimal("85.00"),
        )
        Payment.objects.create(
            sale=self.sale, method=Payment.Method.CASH,
            status=Payment.Status.COMPLETED, amount=Decimal("85.00"),
        )

    def test_page_counts_todays_tender_and_sale(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("Cash", html)
        self.assertIn("$85.00", html)
        self.assertIn("Krystal", html)

    def test_run_cashup_snapshots_and_lists(self):
        self.client.post(self.url, {"action": "cashup"})
        cu = Cashup.objects.get(salon=self.salon)
        self.assertEqual(cu.total, Decimal("85.00"))
        self.assertEqual(cu.tender_totals, {"cash": "85.00"})
        html = self.client.get(self.url).content.decode()
        self.assertIn("Today's cashups", html)
        self.assertIn("$85.00", html)

    def test_cashup_never_locks_the_day(self):
        self.client.post(self.url, {"action": "cashup"})
        self.client.post(self.url, {"action": "cashup"})
        self.assertEqual(Cashup.objects.filter(salon=self.salon).count(), 2)
