from decimal import Decimal

from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.stocktake_sheet import stocktake_sheet
from catalog.variance import VarianceLine, VarianceReport, stocktake_variance
from saloncore.models import Salon


class StocktakeVarianceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def make_product(self, name, price="10.00", sku="", barcode=""):
        return Product.objects.create(
            salon=self.salon, name=name, sku=sku, barcode=barcode,
            price=Decimal(price),
        )

    def move(self, product, delta):
        return StockMovement.objects.create(
            product=product, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=delta,
        )

    def report(self, counts):
        return stocktake_variance(stocktake_sheet(self.salon), counts)

    def test_no_variance(self):
        shampoo = self.make_product("Shampoo", price="10.00")
        self.move(shampoo, 5)
        before = StockMovement.objects.count()
        report = self.report({shampoo: 5})
        self.assertIsInstance(report, VarianceReport)
        self.assertEqual(len(report), 1)
        line = report.lines[0]
        self.assertIsInstance(line, VarianceLine)
        self.assertEqual(
            (line.expected_stock, line.counted_stock, line.difference,
             line.variance),
            (5, 5, 0, 0),
        )
        self.assertTrue(line.is_match)
        self.assertFalse(report.has_variance)
        self.assertEqual(report.total_expected, 5)
        self.assertEqual(report.total_counted, 5)
        self.assertEqual(report.total_difference, 0)
        self.assertEqual(report.total_retail_value_impact, Decimal("0.00"))
        self.assertEqual(report.total_value_impact, Decimal("0.00"))
        self.assertEqual(StockMovement.objects.count(), before)

    def test_shortage(self):
        shampoo = self.make_product(
            "Shampoo", price="10.00", sku="SH-001", barcode="012345678905"
        )
        self.move(shampoo, 10)
        before = StockMovement.objects.count()
        report = self.report({shampoo: 6})
        line = report.lines[0]
        self.assertEqual((line.name, line.sku, line.barcode),
                         ("Shampoo", "SH-001", "012345678905"))
        self.assertEqual((line.expected_stock, line.counted_stock,
                          line.difference), (10, 6, -4))
        self.assertTrue(line.is_shortage)
        self.assertEqual(line.unit_price, Decimal("10.00"))
        self.assertEqual(line.retail_price, Decimal("10.00"))
        self.assertEqual(line.retail_value_impact, Decimal("-40.00"))
        self.assertEqual(line.value_impact, Decimal("-40.00"))
        self.assertEqual(report.total_shortage_units, 4)
        self.assertEqual(report.total_shortage_value, Decimal("-40.00"))
        self.assertEqual(report.total_overage_units, 0)
        self.assertEqual(report.shortage_count, 1)
        # Read-only: no reconciling movement was written.
        self.assertEqual(StockMovement.objects.count(), before)
        self.assertEqual(shampoo.current_stock, 10)

    def test_overage(self):
        conditioner = self.make_product("Conditioner", price="2.50")
        self.move(conditioner, 4)
        report = self.report({conditioner.pk: 7})
        line = report.lines[0]
        self.assertEqual((line.expected_stock, line.counted_stock,
                          line.difference), (4, 7, 3))
        self.assertTrue(line.is_overage)
        self.assertEqual(line.retail_value_impact, Decimal("7.50"))
        self.assertEqual(report.total_overage_units, 3)
        self.assertEqual(report.total_overage_value, Decimal("7.50"))
        self.assertEqual(report.total_shortage_units, 0)
        self.assertEqual(report.overage_count, 1)

    def test_value_impact_totals_mix_shortage_and_overage(self):
        a = self.make_product("A", price="10.00")
        self.move(a, 10)  # counted 6 -> -4 -> -40.00
        b = self.make_product("B", price="20.00")
        self.move(b, 2)   # counted 5 -> +3 -> +60.00
        c = self.make_product("C", price="5.00")
        self.move(c, 3)   # counted 3 -> 0 -> 0.00
        before = StockMovement.objects.count()
        # Keys by barcode/SKU path also covered via product keys here;
        # sheet order (name) is preserved.
        report = self.report({a: 6, b: 5, c: 3})
        self.assertEqual([line.product for line in report.lines], [a, b, c])
        self.assertEqual(report.rows, report.lines)
        self.assertEqual(report.total_expected, 15)
        self.assertEqual(report.total_counted, 14)
        self.assertEqual(report.total_difference, -1)
        self.assertEqual(report.total_retail_value_impact, Decimal("20.00"))
        self.assertEqual(
            report.total_retail_value_impact,
            report.total_shortage_value + report.total_overage_value,
        )
        self.assertEqual(report.total_shortage_value, Decimal("-40.00"))
        self.assertEqual(report.total_overage_value, Decimal("60.00"))
        self.assertEqual(report.total_shortage_units, 4)
        self.assertEqual(report.total_overage_units, 3)
        self.assertEqual(
            (report.shortage_count, report.overage_count,
             report.matched_count, report.variance_count),
            (1, 1, 1, 2),
        )
        self.assertTrue(report.has_variance)
        self.assertEqual(StockMovement.objects.count(), before)

    def test_counts_by_code_and_salon_form(self):
        shampoo = self.make_product(
            "Shampoo", price="19.99", sku="SH-001", barcode="012345678905"
        )
        self.move(shampoo, 3)
        by_barcode = stocktake_variance(self.salon, {"012345678905": 2})
        self.assertEqual(by_barcode.lines[0].difference, -1)
        self.assertEqual(
            by_barcode.lines[0].retail_value_impact, Decimal("-19.99")
        )
        by_sku = stocktake_variance(
            stocktake_sheet(self.salon), {"SH-001": 4}
        )
        self.assertEqual(by_sku.lines[0].difference, 1)

    def test_invalid_counts_raise_and_write_nothing(self):
        shampoo = self.make_product("Shampoo")
        self.move(shampoo, 2)
        sheet = stocktake_sheet(self.salon)
        for bad in ({shampoo: -1}, {shampoo: True}, {99999: 1},
                    {"unknown": 1}, {}):
            with self.assertRaises(ValueError):
                stocktake_variance(sheet, bad)
        self.assertEqual(
            StockMovement.objects.filter(
                kind=StockMovement.Kind.STOCKTAKE).count(), 0)
