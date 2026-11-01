from decimal import Decimal

from django.test import TestCase

from catalog.models import Product, StockMovement
from checkout.models import Payment, Receipt, Sale, SaleItem
from checkout.payments import CashProvider, ExternalTenderProvider, PaymentProvider, PaymentResult
from checkout.sales import add_product_item, add_series_item, add_service_item, complete_sale, create_sale
from checkout.void import void_sale
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory


class _FailingProvider(PaymentProvider):
    name = "cash"

    def charge(self, amount, reference=""):
        return PaymentResult(success=False, status="failed", amount=amount, reference=reference, message="declined")

    def refund(self, payment, amount):
        return PaymentResult(success=False, status="failed", amount=amount)


class SaleServiceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.client = Client.objects.create(salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(category=category, name="Haircut", service_minutes=45)
        self.product = Product.objects.create(salon=self.salon, name="Shampoo", price=Decimal("24.00"))
        StockMovement.objects.create(product=self.product, kind=StockMovement.Kind.RECEIVE, quantity_delta=10)

    def _stocked_sale(self):
        sale = create_sale(self.salon, client=self.client)
        add_service_item(sale, Decimal("85.00"), service=self.service)
        add_product_item(sale, self.product, quantity=2)
        return sale

    def test_create_and_items_totals_exact_decimal(self):
        sale = self._stocked_sale()
        self.assertEqual(sale.status, Sale.Status.OPEN)
        self.assertEqual(sale.client, self.client)
        self.assertEqual(sale.total, Decimal("133.00"))
        self.assertIsInstance(sale.total, Decimal)
        items = list(sale.items.all())
        self.assertEqual(items[0].description, "Haircut")
        self.assertEqual(items[0].line_total, Decimal("85.00"))
        self.assertEqual(items[1].unit_price, Decimal("24.00"))
        self.assertEqual(items[1].line_total, Decimal("48.00"))
        with self.assertRaises(ValueError):
            add_service_item(sale, 9.99)  # float money is rejected

    def test_create_sale_without_client_and_cross_salon_client_rejected(self):
        self.assertIsNone(create_sale(self.salon).client)
        other = Client.objects.create(salon=Salon.objects.create(name="Other"), first_name="A", last_name="B")
        with self.assertRaises(ValueError):
            create_sale(self.salon, client=other)

    def test_series_item_totals_kind_persists_and_links_neither(self):
        sale = create_sale(self.salon, client=self.client)
        add_service_item(sale, Decimal("85.00"), service=self.service)
        item = add_series_item(
            sale, Decimal("200.00"), description="Blowout Series x4", quantity=1
        )
        self.assertEqual(item.kind, SaleItem.Kind.SERIES)
        self.assertEqual(item.kind, "series")
        self.assertIsNone(item.service)
        self.assertIsNone(item.product)
        self.assertEqual(item.description, "Blowout Series x4")
        self.assertEqual(item.unit_price, Decimal("200.00"))
        self.assertEqual(item.line_total, Decimal("200.00"))
        self.assertEqual(sale.total, Decimal("285.00"))
        item.refresh_from_db()
        self.assertEqual(item.kind, "series")
        self.assertIsNone(item.service_id)
        self.assertIsNone(item.product_id)
        with self.assertRaises(ValueError):
            add_series_item(sale, 9.99, description="Float")  # float money rejected

    def test_series_item_completes_without_moving_stock(self):
        sale = create_sale(self.salon, client=self.client)
        add_series_item(sale, Decimal("150.00"), description="Colour Series", quantity=2)
        receipt = complete_sale(sale, CashProvider())
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.COMPLETED)
        self.assertEqual(sale.payments.get().amount, Decimal("300.00"))
        self.assertEqual(receipt.total, Decimal("300.00"))
        self.assertEqual(receipt.lines[0]["kind"], "series")
        self.assertEqual(StockMovement.objects.filter(kind=StockMovement.Kind.SALE).count(), 0)

    def test_completion_via_cash_builds_receipt_and_moves_stock(self):
        sale = self._stocked_sale()
        receipt = complete_sale(sale, CashProvider())
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.COMPLETED)
        self.assertIsNotNone(sale.completed_at)
        payment = sale.payments.get()
        self.assertEqual((payment.method, payment.status, payment.amount), (Payment.Method.CASH, "completed", Decimal("133.00")))
        self.assertEqual(self.product.current_stock, 8)
        movement = StockMovement.objects.get(product=self.product, kind=StockMovement.Kind.SALE)
        self.assertEqual(movement.quantity_delta, -2)
        self.assertIsInstance(receipt, Receipt)
        self.assertEqual(receipt.total, Decimal("133.00"))
        self.assertEqual(len(receipt.lines), 2)
        self.assertEqual(receipt.tender, [{"method": "cash", "amount": "133.00", "status": "completed"}])

    def test_completion_via_external_provider(self):
        sale = self._stocked_sale()
        complete_sale(sale, ExternalTenderProvider())
        self.assertEqual(sale.payments.get().method, Payment.Method.EXTERNAL)
        self.assertEqual(self.product.current_stock, 8)

    def test_failed_charge_leaves_sale_open_stock_and_receipt_untouched(self):
        sale = self._stocked_sale()
        with self.assertRaises(ValueError):
            complete_sale(sale, _FailingProvider())
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.OPEN)
        self.assertEqual(self.product.current_stock, 10)
        self.assertEqual(StockMovement.objects.filter(kind=StockMovement.Kind.SALE).count(), 0)
        self.assertEqual(Receipt.objects.filter(sale=sale).count(), 0)
        self.assertEqual(sale.payments.get().status, Payment.Status.FAILED)
        # The open sale can still be settled afterwards.
        complete_sale(sale, CashProvider())
        self.assertEqual(self.product.current_stock, 8)

    def test_completed_sale_can_be_voided_without_losing_records(self):
        sale = self._stocked_sale()
        complete_sale(sale, CashProvider())
        void_sale(sale, "rung up twice")
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.VOIDED)
        self.assertEqual(SaleItem.objects.filter(sale=sale).count(), 2)
        self.assertEqual(Payment.objects.filter(sale=sale).count(), 1)
        self.assertTrue(Receipt.objects.filter(sale=sale).exists())

    def test_guards_empty_completed_and_item_after_completion(self):
        sale = create_sale(self.salon)
        with self.assertRaises(ValueError):
            complete_sale(sale, CashProvider())
        add_service_item(sale, Decimal("10.00"), description="Trim")
        complete_sale(sale, CashProvider())
        with self.assertRaises(ValueError):
            complete_sale(sale, CashProvider())
        with self.assertRaises(ValueError):
            add_product_item(sale, self.product)
