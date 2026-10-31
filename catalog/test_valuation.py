from decimal import Decimal

from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.valuation import StockValuation, ValuationRow, stock_valuation
from saloncore.models import Salon


class StockValuationTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def make_product(self, name, price="24.00", sku="", barcode="", salon=None, active=True):
        return Product.objects.create(
            salon=salon or self.salon,
            name=name,
            sku=sku,
            barcode=barcode,
            price=Decimal(price),
            active=active,
        )

    def move(self, product, delta, kind=StockMovement.Kind.RECEIVE):
        return StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta
        )

    def test_on_hand_and_value_derived_from_movements(self):
        product = self.make_product("Shampoo", price="10.00", sku="SH-001", barcode="012345678905")
        self.move(product, 10)
        self.move(product, -3, kind=StockMovement.Kind.SALE)
        self.move(product, -1, kind=StockMovement.Kind.ADJUSTMENT)
        report = stock_valuation(self.salon)
        self.assertIsInstance(report, StockValuation)
        self.assertEqual(len(report.rows), 1)
        row = report.rows[0]
        self.assertIsInstance(row, ValuationRow)
        self.assertEqual(row.product, product)
        self.assertEqual(row.sku, "SH-001")
        self.assertEqual(row.barcode, "012345678905")
        self.assertEqual(row.on_hand, 6)
        self.assertEqual(row.current_stock, 6)
        self.assertEqual(row.unit_price, Decimal("10.00"))
        self.assertEqual(row.price, Decimal("10.00"))
        self.assertEqual(row.retail_value, Decimal("60.00"))
        self.assertEqual(row.value, Decimal("60.00"))

    def test_salon_wide_totals_sum_all_rows(self):
        a = self.make_product("A", price="10.00")
        self.move(a, 3)
        b = self.make_product("B", price="2.50")
        self.move(b, 4)
        report = stock_valuation(self.salon)
        self.assertEqual(report.total_on_hand, 7)
        self.assertEqual(report.total_units, 7)
        self.assertEqual(report.total_retail_value, Decimal("40.00"))
        self.assertEqual(report.total_value, Decimal("40.00"))
        self.assertEqual(
            report.total_retail_value,
            sum((r.retail_value for r in report.rows), Decimal("0.00")),
        )

    def test_product_with_no_movements_is_zero_value_row(self):
        self.make_product("Never Stocked", price="15.00")
        report = stock_valuation(self.salon)
        self.assertEqual(len(report.rows), 1)
        self.assertEqual(report.rows[0].on_hand, 0)
        self.assertEqual(report.rows[0].retail_value, Decimal("0.00"))
        self.assertEqual(report.total_retail_value, Decimal("0.00"))

    def test_inactive_products_are_excluded(self):
        active = self.make_product("Active", price="10.00")
        self.move(active, 2)
        inactive = self.make_product("Inactive", price="10.00", active=False)
        self.move(inactive, 100)
        report = stock_valuation(self.salon)
        self.assertEqual([r.product for r in report.rows], [active])
        self.assertEqual(report.total_on_hand, 2)
        self.assertEqual(report.total_retail_value, Decimal("20.00"))

    def test_only_the_given_salons_products_are_valued(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = self.make_product("Foreign", salon=other)
        self.move(foreign, 5)
        own = self.make_product("Own")
        self.move(own, 1)
        report = stock_valuation(self.salon)
        self.assertEqual([r.product for r in report.rows], [own])
        self.assertEqual(report.salon_id, self.salon.pk)
        other_report = stock_valuation(other)
        self.assertEqual([r.product for r in other_report.rows], [foreign])

    def test_rows_ordered_by_retail_value_descending_then_name(self):
        low = self.make_product("Low", price="5.00")
        self.move(low, 1)
        high = self.make_product("High", price="5.00")
        self.move(high, 10)
        beta = self.make_product("Beta", price="10.00")
        self.move(beta, 1)
        alpha = self.make_product("Alpha", price="10.00")
        self.move(alpha, 1)
        report = stock_valuation(self.salon)
        self.assertEqual(
            [r.product for r in report.rows], [high, alpha, beta, low]
        )
        self.assertEqual(
            [r.retail_value for r in report.rows],
            [Decimal("50.00"), Decimal("10.00"), Decimal("10.00"), Decimal("5.00")],
        )

    def test_fractional_price_multiplies_exactly(self):
        product = self.make_product("Serum", price="19.99")
        self.move(product, 3)
        report = stock_valuation(self.salon)
        self.assertEqual(report.rows[0].retail_value, Decimal("59.97"))

    def test_negative_on_hand_reports_negative_value_unclamped(self):
        product = self.make_product("Oversold", price="10.00")
        self.move(product, -2, kind=StockMovement.Kind.SALE)
        report = stock_valuation(self.salon)
        self.assertEqual(report.rows[0].on_hand, -2)
        self.assertEqual(report.rows[0].retail_value, Decimal("-20.00"))
        self.assertEqual(report.total_retail_value, Decimal("-20.00"))

    def test_empty_salon_has_zero_totals_and_no_rows(self):
        report = stock_valuation(self.salon)
        self.assertEqual(report.rows, ())
        self.assertEqual(len(report), 0)
        self.assertEqual(list(report), [])
        self.assertEqual(report.total_on_hand, 0)
        self.assertEqual(report.total_retail_value, Decimal("0.00"))

    def test_stocktake_movements_count_toward_valuation(self):
        product = self.make_product("Counted", price="20.00")
        self.move(product, 10)
        self.move(product, -4, kind=StockMovement.Kind.STOCKTAKE)
        report = stock_valuation(self.salon)
        self.assertEqual(report.rows[0].on_hand, 6)
        self.assertEqual(report.rows[0].retail_value, Decimal("120.00"))
