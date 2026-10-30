from decimal import Decimal

from django.test import TestCase

from catalog.models import Product
from checkout.models import Sale, SaleItem
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory


class SaleModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )

    def test_creation_defaults_and_fks(self):
        sale = Sale.objects.create(salon=self.salon, client=self.client)
        sale.refresh_from_db()
        self.assertEqual(sale.salon, self.salon)
        self.assertEqual(sale.client, self.client)
        self.assertIn(sale, list(self.salon.sales.all()))
        self.assertIn(sale, list(self.client.sales.all()))
        self.assertEqual(sale.status, Sale.Status.OPEN)
        self.assertEqual(sale.status, "open")
        self.assertIsNotNone(sale.created_at)
        self.assertIsNone(sale.completed_at)

    def test_client_is_optional(self):
        sale = Sale.objects.create(salon=self.salon)
        self.assertIsNone(sale.client)

    def test_status_choices(self):
        self.assertEqual(
            [c[0] for c in Sale.Status.choices],
            ["open", "completed", "voided"],
        )

    def test_empty_sale_total_is_zero(self):
        sale = Sale.objects.create(salon=self.salon)
        self.assertEqual(sale.total, Decimal("0.00"))

    def test_str(self):
        sale = Sale.objects.create(salon=self.salon)
        self.assertIn("Example Salon", str(sale))
        self.assertIn("open", str(sale))


class SaleItemModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts"
        )
        self.service = Service.objects.create(
            category=self.category, name="Haircut", service_minutes=45
        )
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", price=Decimal("24.00")
        )
        self.sale = Sale.objects.create(salon=self.salon, client=self.client)

    def test_service_item_and_line_total(self):
        item = SaleItem.objects.create(
            sale=self.sale, kind=SaleItem.Kind.SERVICE, service=self.service,
            description="Haircut", quantity=1, unit_price=Decimal("85.00"),
        )
        self.assertEqual(item.sale, self.sale)
        self.assertIn(item, list(self.sale.items.all()))
        self.assertEqual(item.service, self.service)
        self.assertIsNone(item.product)
        self.assertEqual(item.line_total, Decimal("85.00"))

    def test_product_item_quantity_multiplies(self):
        item = SaleItem.objects.create(
            sale=self.sale, kind=SaleItem.Kind.PRODUCT, product=self.product,
            description="Shampoo", quantity=2, unit_price=Decimal("24.00"),
        )
        self.assertEqual(item.product, self.product)
        self.assertIsNone(item.service)
        self.assertEqual(item.line_total, Decimal("48.00"))

    def test_kind_choices(self):
        self.assertEqual(
            [c[0] for c in SaleItem.Kind.choices], ["service", "product"]
        )

    def test_quantity_defaults_to_one(self):
        item = SaleItem.objects.create(
            sale=self.sale, kind=SaleItem.Kind.SERVICE,
            description="Haircut", unit_price=Decimal("85.00"),
        )
        item.refresh_from_db()
        self.assertEqual(item.quantity, 1)

    def test_sale_total_sums_items(self):
        SaleItem.objects.create(
            sale=self.sale, kind="service", service=self.service,
            description="Haircut", unit_price=Decimal("85.00"),
        )
        SaleItem.objects.create(
            sale=self.sale, kind="product", product=self.product,
            description="Shampoo", quantity=2, unit_price=Decimal("24.00"),
        )
        self.assertEqual(self.sale.total, Decimal("133.00"))

    def test_sale_total_is_computed_not_stored(self):
        concrete = [f.name for f in Sale._meta.get_fields() if getattr(f, "concrete", False)]
        self.assertNotIn("total", concrete)

    def test_items_cascade_on_sale_delete(self):
        SaleItem.objects.create(
            sale=self.sale, kind="service", description="Haircut",
            unit_price=Decimal("85.00"),
        )
        self.sale.delete()
        self.assertEqual(SaleItem.objects.count(), 0)

    def test_snapshot_survives_product_delete(self):
        SaleItem.objects.create(
            sale=self.sale, kind="product", product=self.product,
            description="Shampoo", quantity=1, unit_price=Decimal("24.00"),
        )
        self.product.delete()
        item = SaleItem.objects.get()
        self.assertIsNone(item.product)
        self.assertEqual(item.description, "Shampoo")
        self.assertEqual(item.line_total, Decimal("24.00"))
