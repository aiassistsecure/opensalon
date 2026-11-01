from decimal import Decimal

from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.product_sales import (
    ProductSalesReport,
    ProductSalesRow,
    product_sales,
)
from checkout.models import Sale, SaleItem
from saloncore.models import Salon


class ProductSalesTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def make_product(self, name, price="10.00", salon=None, active=True, **kw):
        return Product.objects.create(
            salon=salon or self.salon, name=name,
            price=Decimal(price), active=active, **kw,
        )

    def move(self, product, delta, kind=StockMovement.Kind.RECEIVE):
        return StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta
        )

    def sell(self, product, quantity, unit_price, status=Sale.Status.COMPLETED,
             salon=None, kind=SaleItem.Kind.PRODUCT):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=status
        )
        return SaleItem.objects.create(
            sale=sale, kind=kind, product=product,
            description=product.name if product else "",
            quantity=quantity, unit_price=Decimal(unit_price),
        )

    def row_for(self, report, product):
        return next(r for r in report.rows if r.product == product)

    def test_units_and_revenue_from_completed_product_lines(self):
        product = self.make_product("Shampoo", sku="SH-001",
                                    barcode="012345678905")
        self.sell(product, 2, "10.00")
        self.sell(product, 3, "12.00")  # snapshot price, not product price
        report = product_sales(self.salon)
        self.assertIsInstance(report, ProductSalesReport)
        row = self.row_for(report, product)
        self.assertIsInstance(row, ProductSalesRow)
        self.assertEqual(row.sku, "SH-001")
        self.assertEqual(row.barcode, "012345678905")
        self.assertEqual(row.units_sold, 5)
        self.assertEqual(row.retail_revenue, Decimal("56.00"))
        self.assertEqual(report.salon_id, self.salon.pk)

    def test_open_and_voided_sales_never_count(self):
        product = self.make_product("Shampoo")
        self.sell(product, 1, "10.00")
        self.sell(product, 100, "99.00", status=Sale.Status.OPEN)
        self.sell(product, 100, "99.00", status=Sale.Status.VOIDED)
        row = self.row_for(product_sales(self.salon), product)
        self.assertEqual(row.units_sold, 1)
        self.assertEqual(row.retail_revenue, Decimal("10.00"))

    def test_service_series_and_unlinked_lines_never_count(self):
        product = self.make_product("Shampoo")
        self.sell(product, 2, "10.00")
        self.sell(None, 5, "50.00", kind=SaleItem.Kind.SERVICE)
        self.sell(None, 5, "50.00", kind=SaleItem.Kind.SERIES)
        self.sell(None, 5, "50.00", kind=SaleItem.Kind.PRODUCT)
        row = self.row_for(product_sales(self.salon), product)
        self.assertEqual(row.units_sold, 2)
        self.assertEqual(row.retail_revenue, Decimal("20.00"))

    def test_current_and_average_stock_are_movement_derived(self):
        product = self.make_product("Shampoo")
        self.move(product, 10)
        self.move(product, 10)
        self.move(product, -5, kind=StockMovement.Kind.SALE)
        row = self.row_for(product_sales(self.salon), product)
        self.assertEqual(row.current_stock, 15)
        # Levels after each movement: 10, 20, 15 -> mean 15.
        self.assertEqual(row.average_stock, Decimal("15.0000"))

    def test_stock_turns_is_units_over_average_stock(self):
        product = self.make_product("Shampoo")
        self.move(product, 10)
        self.move(product, 10)
        self.move(product, -5, kind=StockMovement.Kind.SALE)
        self.sell(product, 5, "10.00")
        row = self.row_for(product_sales(self.salon), product)
        self.assertEqual(row.stock_turns, Decimal("0.3333"))

    def test_zero_average_stock_turns_are_zero_never_an_error(self):
        sold_unstocked = self.make_product("Sold Unstocked")
        self.sell(sold_unstocked, 4, "10.00")
        never_stocked = self.make_product("Never Stocked")
        report = product_sales(self.salon)
        for product in (sold_unstocked, never_stocked):
            row = self.row_for(report, product)
            self.assertEqual(row.average_stock, Decimal("0"))
            self.assertEqual(row.stock_turns, Decimal("0.0000"))
        self.assertEqual(
            self.row_for(report, sold_unstocked).units_sold, 4)

    def test_unsold_and_inactive_products_still_get_rows(self):
        unsold = self.make_product("Unsold")
        self.move(unsold, 3)
        retired = self.make_product("Retired", active=False)
        self.sell(retired, 1, "7.50")
        report = product_sales(self.salon)
        self.assertEqual(
            {r.product for r in report.rows}, {unsold, retired})
        row = self.row_for(report, unsold)
        self.assertEqual(row.units_sold, 0)
        self.assertEqual(row.retail_revenue, Decimal("0.00"))
        self.assertEqual(row.current_stock, 3)

    def test_only_the_given_salons_products_and_sales_count(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = self.make_product("Foreign", salon=other)
        self.sell(foreign, 9, "99.00", salon=other)
        own = self.make_product("Own")
        self.sell(own, 1, "10.00")
        # A foreign sale line pointing at our product must not count:
        # the sale's salon is the scope, not just the product's.
        self.sell(own, 50, "99.00", salon=other)
        report = product_sales(self.salon)
        self.assertEqual([r.product for r in report.rows], [own])
        self.assertEqual(report.rows[0].units_sold, 1)

    def test_rows_ordered_by_revenue_then_units_then_name(self):
        low = self.make_product("Low")
        self.sell(low, 1, "5.00")
        high = self.make_product("High")
        self.sell(high, 1, "50.00")
        beta = self.make_product("Beta")
        self.sell(beta, 2, "5.00")
        alpha = self.make_product("Alpha")
        self.sell(alpha, 2, "5.00")
        report = product_sales(self.salon)
        self.assertEqual(
            [r.product for r in report.rows], [high, alpha, beta, low])

    def test_totals_sum_all_rows(self):
        a = self.make_product("A")
        self.sell(a, 2, "10.00")
        b = self.make_product("B")
        self.sell(b, 3, "2.50")
        report = product_sales(self.salon)
        self.assertEqual(report.total_units_sold, 5)
        self.assertEqual(report.total_retail_revenue, Decimal("27.50"))
        self.assertEqual(len(report), 2)
        self.assertEqual(list(report), list(report.rows))

    def test_empty_salon_has_no_rows_and_zero_totals(self):
        report = product_sales(self.salon)
        self.assertEqual(report.rows, ())
        self.assertEqual(report.total_units_sold, 0)
        self.assertEqual(report.total_retail_revenue, Decimal("0.00"))

    def test_report_is_read_only(self):
        product = self.make_product("Shampoo")
        self.move(product, 10)
        self.sell(product, 2, "10.00")
        before = (
            Product.objects.count(), StockMovement.objects.count(),
            Sale.objects.count(), SaleItem.objects.count(),
        )
        product_sales(self.salon)
        after = (
            Product.objects.count(), StockMovement.objects.count(),
            Sale.objects.count(), SaleItem.objects.count(),
        )
        self.assertEqual(before, after)
