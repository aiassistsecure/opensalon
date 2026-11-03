import csv
import io
from datetime import date, datetime, time, timedelta, timezone as dt_tz
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.margin import product_margin
from catalog.margin_export import (
    MARGIN_FIELDNAMES,
    export_product_margin,
    export_product_margin_csv,
)
from catalog.models import Product, StockMovement
from catalog.product_sales import product_sales
from catalog.product_sales_export import (
    PRODUCT_SALES_FIELDNAMES,
    export_product_sales_csv,
)
from checkout.models import Sale, SaleItem
from saloncore.models import Salon

DAY = date(2026, 10, 3)
BEFORE = DAY - timedelta(days=5)
AFTER = DAY + timedelta(days=5)


def at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=dt_tz.utc)


class WindowedFixtures(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"),
            cost_price=Decimal("6.00"))
        for delta in (10, 10, -5):
            StockMovement.objects.create(
                product=self.product, kind=StockMovement.Kind.RECEIVE,
                quantity_delta=delta)
        # In-window: 2 units @10 (completed_at on DAY).
        self.sell(2, "10.00", completed=at(DAY))
        # Before window: 3 units @10 (created == completed BEFORE).
        self.sell(3, "10.00", completed=at(BEFORE))
        # After window, no completed_at: created_at decides (AFTER).
        self.sell(1, "10.00", completed=None, created=at(AFTER))

    def sell(self, qty, price, completed, created=None):
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.PRODUCT, product=self.product,
            description="Shampoo", quantity=qty,
            unit_price=Decimal(price))
        updates = {"completed_at": completed}
        if created is not None:
            updates["created_at"] = created
        elif completed is not None:
            updates["created_at"] = completed - timedelta(days=30)
        Sale.objects.filter(pk=sale.pk).update(**updates)
        return sale

    def row(self, report):
        return report.rows[0]


class ProductSalesWindowedTests(WindowedFixtures):
    def test_windowed_units_and_revenue_only(self):
        report = product_sales(self.salon, start=DAY, end=DAY)
        row = self.row(report)
        self.assertEqual(row.units_sold, 2)
        self.assertEqual(row.retail_revenue, Decimal("20.00"))
        self.assertEqual(report.total_units_sold, 2)
        self.assertEqual(report.total_retail_revenue, Decimal("20.00"))

    def test_alias_kwargs_and_string_bounds(self):
        a = product_sales(self.salon, start_date=DAY, end_date=DAY)
        b = product_sales(self.salon, "2026-10-03", "2026-10-03")
        self.assertEqual(self.row(a).units_sold, 2)
        self.assertEqual(self.row(b).units_sold, 2)

    def test_completed_at_wins_and_created_at_fallback(self):
        # The DAY sale's created_at is 30 days earlier: counting it
        # proves completed_at wins. A window on AFTER counts the
        # sale with no completed_at via its created_at.
        self.assertEqual(
            self.row(product_sales(self.salon, start=AFTER, end=AFTER))
            .units_sold, 1)
        self.assertEqual(
            self.row(product_sales(self.salon, start=BEFORE, end=BEFORE))
            .units_sold, 3)

    def test_one_sided_windows(self):
        self.assertEqual(
            self.row(product_sales(self.salon, start=DAY)).units_sold, 3)
        self.assertEqual(
            self.row(product_sales(self.salon, end=DAY)).units_sold, 5)

    def test_stock_figures_stay_all_time_and_are_documented(self):
        default = self.row(product_sales(self.salon))
        windowed_report = product_sales(self.salon, start=DAY, end=DAY)
        w = self.row(windowed_report)
        self.assertEqual(default.units_sold, 6)
        self.assertEqual(w.current_stock, default.current_stock)
        self.assertEqual(w.average_stock, default.average_stock)
        self.assertEqual(w.current_stock, 15)
        self.assertEqual(w.average_stock, Decimal("15.0000"))
        # Turns are all-time (6 / 15), not windowed (2 / 15).
        self.assertEqual(w.stock_turns, default.stock_turns)
        self.assertEqual(w.stock_turns, Decimal("0.4000"))
        self.assertEqual(w.stock_scope, "all_time")
        self.assertEqual(w.sales_scope, "windowed")
        self.assertEqual((w.start_date, w.end_date), (DAY, DAY))
        self.assertEqual(windowed_report.stock_scope, "all_time")
        self.assertEqual(windowed_report.sales_scope, "windowed")
        self.assertEqual(
            (windowed_report.start_date, windowed_report.end_date),
            (DAY, DAY))

    def test_reversed_window_raises(self):
        with self.assertRaises(ValueError):
            product_sales(self.salon, start=AFTER, end=DAY)

    def test_default_is_all_time_and_documented_as_such(self):
        report = product_sales(self.salon)
        row = self.row(report)
        self.assertEqual((row.units_sold, row.retail_revenue),
                         (6, Decimal("60.00")))
        self.assertIsNone(report.start_date)
        self.assertIsNone(report.end_date)
        self.assertEqual(report.sales_scope, "all_time")
        self.assertEqual(row.stock_scope, "all_time")


class ProductMarginWindowedTests(WindowedFixtures):
    def test_margin_reuses_windowed_sales_verbatim(self):
        report = product_margin(self.salon, start=DAY, end=DAY)
        row = report.rows[0]
        sales_row = product_sales(self.salon, start=DAY, end=DAY).rows[0]
        self.assertEqual(row.units_sold, sales_row.units_sold)
        self.assertEqual(row.retail_revenue, sales_row.retail_revenue)
        self.assertEqual(row.cost, Decimal("12.00"))
        self.assertEqual(row.margin, Decimal("8.00"))
        self.assertEqual(row.margin_percent, Decimal("40.00"))
        self.assertEqual((report.start_date, report.end_date), (DAY, DAY))
        self.assertEqual(report.sales_scope, "windowed")

    def test_margin_default_is_all_time(self):
        report = product_margin(self.salon)
        self.assertEqual(report.rows[0].units_sold, 6)
        self.assertEqual(report.rows[0].margin, Decimal("24.00"))
        self.assertIsNone(report.start_date)
        self.assertEqual(report.sales_scope, "all_time")


class WindowedExportAndCommandTests(WindowedFixtures):
    def test_sales_export_default_byte_shape_unchanged(self):
        text = export_product_sales_csv(self.salon)
        self.assertEqual(text.splitlines()[0].split(","),
                         PRODUCT_SALES_FIELDNAMES)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(rows[0]["units_sold"], "6")
        self.assertEqual(rows[0]["stock_turns"], "0.4000")

    def test_sales_export_windowed_documents_window_and_stock_scope(self):
        text = export_product_sales_csv(
            self.salon, start_date=DAY, end_date=DAY)
        header = text.splitlines()[0].split(",")
        self.assertEqual(header[:len(PRODUCT_SALES_FIELDNAMES)],
                         PRODUCT_SALES_FIELDNAMES)
        self.assertEqual(header[len(PRODUCT_SALES_FIELDNAMES):],
                         ["sales_start_date", "sales_end_date", "stock_scope"])
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(rows[0]["units_sold"], "2")
        self.assertEqual(rows[0]["current_stock"], "15")
        self.assertEqual(rows[0]["stock_scope"], "all_time")
        self.assertEqual(rows[0]["sales_start_date"], "2026-10-03")

    def test_margin_export_windowed_and_default(self):
        default = export_product_margin(self.salon)
        self.assertEqual(list(default[0]), MARGIN_FIELDNAMES)
        self.assertEqual(default[0]["units_sold"], 6)
        windowed = export_product_margin(
            self.salon, start_date=DAY, end_date=DAY)
        self.assertEqual(windowed[0]["units_sold"], 2)
        self.assertEqual(windowed[0]["sales_start_date"], "2026-10-03")
        text = export_product_margin_csv(
            self.salon, start_date=DAY, end_date=DAY)
        self.assertEqual(
            text, export_product_margin_csv(
                self.salon, start_date=DAY, end_date=DAY))
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(rows[0]["units_sold"], "2")
        self.assertEqual(
            export_product_margin_csv(self.salon).splitlines()[0].split(","),
            MARGIN_FIELDNAMES)

    def test_commands_windowed_match_services(self):
        out = io.StringIO()
        call_command("export_product_sales", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), export_product_sales_csv(
            self.salon, start_date=DAY, end_date=DAY))
        out = io.StringIO()
        call_command("export_product_margin", salon_id=self.salon.pk,
                     start_date="2026-10-03", end_date="2026-10-03",
                     stdout=out)
        self.assertEqual(out.getvalue(), export_product_margin_csv(
            self.salon, start_date=DAY, end_date=DAY))

    def test_commands_default_match_default_services(self):
        out = io.StringIO()
        call_command("export_product_sales", salon_id=self.salon.pk,
                     stdout=out)
        self.assertEqual(out.getvalue(),
                         export_product_sales_csv(self.salon))
        out = io.StringIO()
        call_command("export_product_margin", salon_id=self.salon.pk,
                     stdout=out)
        self.assertEqual(out.getvalue(),
                         export_product_margin_csv(self.salon))

    def test_commands_reject_bad_and_reversed_dates(self):
        with self.assertRaises(CommandError):
            call_command("export_product_sales", salon_id=self.salon.pk,
                         start_date="not-a-date", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_product_margin", salon_id=self.salon.pk,
                         start_date=AFTER, end_date=DAY,
                         stdout=io.StringIO())
