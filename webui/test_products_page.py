"""The Shelf: products page — derived stock, receiving, adjustments."""
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from catalog.models import Product, StockMovement
from saloncore.models import Salon


class ShelfPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.salon = Salon.objects.create(name="Mint", timezone="America/New_York")
        self.url = reverse("webui:products")
        self.product = Product.objects.create(
            salon=self.salon, name="Yuko Smoothing Conditioner",
            brand_name="Yuko", product_type="RETAIL",
            barcode="850001", price=Decimal("26.00"),
        )
        StockMovement.objects.create(
            product=self.product, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=6, note="Opening stock",
        )

    def test_page_shows_derived_stock(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("Yuko Smoothing Conditioner", html)
        self.assertIn("850001", html)
        self.assertIn("<b>6</b>", html)

    def test_search_narrows_by_barcode(self):
        html = self.client.get(self.url, {"q": "850001"}).content.decode()
        self.assertIn("Yuko Smoothing Conditioner", html)
        html = self.client.get(self.url, {"q": "nope-nothing"}).content.decode()
        self.assertNotIn("Yuko Smoothing Conditioner", html)

    def test_receive_appends_a_movement_and_stock_rises(self):
        self.client.post(self.url, {
            "action": "receive", "product": self.product.pk, "qty": "4",
        })
        self.assertEqual(self.product.current_stock, 10)
        movement = StockMovement.objects.order_by("-id").first()
        self.assertEqual(movement.kind, StockMovement.Kind.RECEIVE)
        self.assertEqual(movement.quantity_delta, 4)

    def test_adjustment_records_reason_and_negative_is_refused(self):
        self.client.post(self.url, {
            "action": "adjust", "product": self.product.pk,
            "delta": "-2", "reason": "Damaged bottle",
        })
        self.assertEqual(self.product.current_stock, 4)
        self.client.post(self.url, {
            "action": "adjust", "product": self.product.pk,
            "delta": "-99", "reason": "Write-off",
        })
        self.assertEqual(self.product.current_stock, 4)
