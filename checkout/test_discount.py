import datetime
from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from catalog.models import Product, StockMovement
from checkout.models import Sale, SaleItem
from checkout.payments import CashProvider
from checkout.sales import (
    add_product_item,
    add_series_item,
    add_service_item,
    apply_discount,
    complete_sale,
    create_sale,
)
from checkout.summary import daily_sales_summary
from saloncore.models import Salon, Service, ServiceCategory


class DiscountModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.sale = Sale.objects.create(salon=self.salon)

    def _item(self, price, qty=1, discount="0.00"):
        return SaleItem.objects.create(
            sale=self.sale, kind="service", description="Haircut",
            quantity=qty, unit_price=Decimal(price),
            discount_amount=Decimal(discount),
        )

    def test_discount_defaults_to_zero_and_persists(self):
        item = self._item("85.00")
        self.sale.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(self.sale.discount_amount, Decimal("0.00"))
        self.assertEqual(item.discount_amount, Decimal("0.00"))
        self.assertEqual(item.subtotal, Decimal("85.00"))
        self.assertEqual(item.line_total, Decimal("85.00"))
        self.assertEqual(self.sale.subtotal, Decimal("85.00"))
        self.assertEqual(self.sale.discount_total, Decimal("0.00"))
        self.assertEqual(self.sale.total, Decimal("85.00"))

    def test_line_and_sale_discounts_net_the_total(self):
        self._item("85.00", discount="10.00")
        self._item("24.00", qty=2)
        Sale.objects.filter(pk=self.sale.pk).update(
            discount_amount=Decimal("5.00")
        )
        self.sale.refresh_from_db()
        # Gross 85 + 48 = 133; discounts 10 (line) + 5 (sale) = 15.
        self.assertEqual(self.sale.subtotal, Decimal("133.00"))
        self.assertEqual(self.sale.discount_total, Decimal("15.00"))
        self.assertEqual(self.sale.total, Decimal("118.00"))
        line = self.sale.items.first()
        self.assertEqual(line.subtotal, Decimal("85.00"))
        self.assertEqual(line.line_total, Decimal("75.00"))

    def test_full_clean_rejects_negative_discounts(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            Sale(salon=self.salon,
                 discount_amount=Decimal("-1.00")).full_clean()
        with self.assertRaises(ValidationError):
            SaleItem(
                sale=self.sale, kind="service", description="X",
                unit_price=Decimal("10.00"),
                discount_amount=Decimal("-0.01"),
            ).full_clean()


class DiscountConstraintSaveTests(TransactionTestCase):
    """StrictConstraints enforces the nonnegative checks on save()."""

    def test_negative_sale_discount_rejected_on_save(self):
        salon = Salon.objects.create(name="Example Salon")
        with self.assertRaises(IntegrityError):
            Sale.objects.create(
                salon=salon, discount_amount=Decimal("-1.00")
            )
        self.assertEqual(Sale.objects.count(), 0)

    def test_negative_item_discount_rejected_on_save(self):
        salon = Salon.objects.create(name="Example Salon")
        sale = Sale.objects.create(salon=salon)
        with self.assertRaises(IntegrityError):
            SaleItem.objects.create(
                sale=sale, kind="service", description="X",
                unit_price=Decimal("10.00"),
                discount_amount=Decimal("-1.00"),
            )
        self.assertEqual(SaleItem.objects.count(), 0)


class DiscountSaleServiceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", price=Decimal("24.00")
        )
        StockMovement.objects.create(
            product=self.product, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=10,
        )

    def test_add_items_record_line_discounts(self):
        sale = create_sale(self.salon)
        svc = add_service_item(
            sale, Decimal("85.00"), service=self.service,
            discount_amount=Decimal("10.00"),
        )
        prod = add_product_item(
            sale, self.product, quantity=2,
            discount_amount=Decimal("8.00"),
        )
        series = add_series_item(
            sale, Decimal("200.00"), description="Series",
            discount_amount=Decimal("20.00"),
        )
        self.assertEqual(svc.line_total, Decimal("75.00"))
        self.assertEqual(prod.line_total, Decimal("40.00"))
        self.assertEqual(series.line_total, Decimal("180.00"))
        self.assertEqual(sale.subtotal, Decimal("333.00"))
        self.assertEqual(sale.discount_total, Decimal("38.00"))
        self.assertEqual(sale.total, Decimal("295.00"))
        svc.refresh_from_db()
        self.assertEqual(svc.discount_amount, Decimal("10.00"))

    def test_line_discount_guards(self):
        sale = create_sale(self.salon)
        with self.assertRaises(ValueError):
            add_service_item(sale, Decimal("85.00"),
                             discount_amount=Decimal("-1.00"))
        with self.assertRaises(ValueError):
            add_service_item(sale, Decimal("85.00"), discount_amount=9.99)
        with self.assertRaises(ValueError):
            # More than the line's subtotal is refused.
            add_service_item(sale, Decimal("85.00"),
                             discount_amount=Decimal("85.01"))
        with self.assertRaises(ValueError):
            add_product_item(sale, self.product,
                             discount_amount=Decimal("24.01"))
        self.assertEqual(SaleItem.objects.count(), 0)
        # A discount equal to the line subtotal is allowed.
        item = add_service_item(sale, Decimal("85.00"),
                                discount_amount=Decimal("85.00"))
        self.assertEqual(item.line_total, Decimal("0.00"))

    def test_apply_discount_sets_and_replaces_sale_discount(self):
        sale = create_sale(self.salon)
        add_service_item(sale, Decimal("85.00"),
                         discount_amount=Decimal("5.00"))
        apply_discount(sale, Decimal("10.00"))
        sale.refresh_from_db()
        self.assertEqual(sale.discount_amount, Decimal("10.00"))
        self.assertEqual(sale.discount_total, Decimal("15.00"))
        self.assertEqual(sale.total, Decimal("70.00"))
        apply_discount(sale, Decimal("20.00"))
        self.assertEqual(sale.discount_amount, Decimal("20.00"))
        self.assertEqual(sale.total, Decimal("60.00"))

    def test_apply_discount_guards(self):
        sale = create_sale(self.salon)
        add_service_item(sale, Decimal("85.00"))
        with self.assertRaises(ValueError):
            apply_discount(sale, Decimal("-1.00"))
        with self.assertRaises(ValueError):
            apply_discount(sale, 9.99)
        with self.assertRaises(ValueError):
            # Ceiling is the line total after line discounts (85).
            apply_discount(sale, Decimal("85.01"))
        sale.refresh_from_db()
        self.assertEqual(sale.discount_amount, Decimal("0.00"))
        complete_sale(sale, CashProvider())
        with self.assertRaises(ValueError):
            apply_discount(sale, Decimal("1.00"))

    def test_completion_charges_net_of_all_discounts(self):
        sale = create_sale(self.salon)
        add_service_item(sale, Decimal("85.00"), service=self.service,
                         discount_amount=Decimal("10.00"))
        add_product_item(sale, self.product, quantity=2)
        apply_discount(sale, Decimal("5.00"))
        receipt = complete_sale(sale, CashProvider())
        sale.refresh_from_db()
        # Gross 133 - 10 (line) - 5 (sale) = 118 settled.
        self.assertEqual(sale.payments.get().amount, Decimal("118.00"))
        self.assertEqual(receipt.total, Decimal("118.00"))
        self.assertEqual(self.product.current_stock, 8)


class DiscountSummaryTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.day = datetime.date(2026, 10, 3)

    def _sale(self, salon, items, sale_discount="0.00",
              status=Sale.Status.COMPLETED):
        sale = Sale.objects.create(
            salon=salon, status=status,
            discount_amount=Decimal(sale_discount),
        )
        for kind, price, qty, discount in items:
            SaleItem.objects.create(
                sale=sale, kind=kind, description=kind,
                unit_price=Decimal(price), quantity=qty,
                discount_amount=Decimal(discount),
            )
        stamp = timezone.make_aware(
            datetime.datetime.combine(self.day, datetime.time(12, 0)),
            datetime.timezone.utc,
        )
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp
        )
        return sale

    def test_empty_day_discount_and_net_are_zero(self):
        result = daily_sales_summary(self.salon, self.day)
        self.assertEqual(result.discount_total, Decimal("0.00"))
        self.assertEqual(result.discount, Decimal("0.00"))
        self.assertEqual(result.net_total, Decimal("0.00"))
        self.assertEqual(result.net, Decimal("0.00"))

    def test_discount_totals_and_net(self):
        self._sale(
            self.salon,
            [("service", "85.00", 1, "10.00"),
             ("product", "20.00", 2, "0.00")],
            sale_discount="5.00",
        )
        self._sale(self.salon, [("series", "100.00", 1, "25.00")])
        result = daily_sales_summary(self.salon, self.day)
        # Gross stays pre-discount: 85 + 40 + 100 = 225.
        self.assertEqual(result.gross_total, Decimal("225.00"))
        self.assertEqual(result.service_total, Decimal("85.00"))
        self.assertEqual(result.retail_total, Decimal("40.00"))
        self.assertEqual(result.series_total, Decimal("100.00"))
        # Discounts: lines 10 + 25, sale-level 5.
        self.assertEqual(result.discount_total, Decimal("40.00"))
        self.assertEqual(result["discount_total"], Decimal("40.00"))
        self.assertEqual(result.net_total, Decimal("185.00"))
        self.assertEqual(result["net"], Decimal("185.00"))

    def test_undiscounted_day_net_equals_gross(self):
        self._sale(self.salon, [("service", "85.00", 1, "0.00")])
        result = daily_sales_summary(self.salon, self.day)
        self.assertEqual(result.discount_total, Decimal("0.00"))
        self.assertEqual(result.net_total, result.gross_total)

    def test_voided_and_other_salon_discounts_excluded(self):
        self._sale(self.salon, [("service", "85.00", 1, "10.00")])
        self._sale(self.salon, [("service", "999.00", 1, "500.00")],
                   sale_discount="100.00", status=Sale.Status.VOIDED)
        self._sale(self.other, [("service", "999.00", 1, "500.00")],
                   sale_discount="100.00")
        result = daily_sales_summary(self.salon, self.day)
        self.assertEqual(result.discount_total, Decimal("10.00"))
        self.assertEqual(result.gross_total, Decimal("85.00"))
        self.assertEqual(result.net_total, Decimal("75.00"))
