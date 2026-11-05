import io
import json
import os
import tempfile
from datetime import date, datetime, time, timedelta, timezone as dt_tz
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.margin_export import (
    MARGIN_FIELDNAMES,
    export_product_margin,
    export_product_margin_csv,
)
from catalog.models import Product
from checkout.models import Sale, SaleItem
from saloncore.models import Salon

DAY = date(2026, 10, 3)


class ExportProductMarginCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.empty = Salon.objects.create(name="Empty Salon")
        product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"),
            cost_price=Decimal("6.00"))
        self.sell(product, 2, "10.00")
        foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999", price=Decimal("1.00"),
            cost_price=Decimal("0.50"))
        self.sell(foreign, 9, "99.00", salon=self.other)

    def sell(self, product, quantity, unit_price, salon=None, on=None):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.PRODUCT, product=product,
            description=product.name, quantity=quantity,
            unit_price=Decimal(unit_price))
        if on is not None:
            when = datetime.combine(on, time(12), tzinfo=dt_tz.utc)
            Sale.objects.filter(pk=sale.pk).update(
                completed_at=when, created_at=when - timedelta(days=30))
        return sale

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_product_margin", salon_id=self.salon.pk,
                     stdout=out)
        text = out.getvalue()
        self.assertEqual(text, export_product_margin_csv(self.salon))
        self.assertEqual(text.splitlines()[0].split(","),
                         MARGIN_FIELDNAMES)
        self.assertIn("Shampoo", text)
        self.assertNotIn("Foreign", text)

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "margin.csv")
            call_command("export_product_margin", salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, export_product_margin_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_product_margin", salon_id=999999,
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "margin.csv")
            with self.assertRaises(CommandError):
                call_command("export_product_margin",
                             salon_id=self.salon.pk, output=path,
                             stdout=io.StringIO())


class ExportProductMarginFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.empty = Salon.objects.create(name="Empty Salon")
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"),
            cost_price=Decimal("6.00"))
        # 2 units on DAY (in the window used below).
        self.sell(self.product, 2, "10.00", on=DAY)
        # 3 units well before DAY (outside that window).
        self.sell(self.product, 3, "10.00",
                  on=DAY - timedelta(days=5))

    def sell(self, product, quantity, unit_price, on=None):
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.PRODUCT, product=product,
            description=product.name, quantity=quantity,
            unit_price=Decimal(unit_price))
        if on is not None:
            when = datetime.combine(on, time(12), tzinfo=dt_tz.utc)
            Sale.objects.filter(pk=sale.pk).update(
                completed_at=when, created_at=when - timedelta(days=30))
        return sale

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command("export_product_margin", salon_id=self.salon.pk,
                     stdout=out)
        self.assertEqual(out.getvalue(),
                         export_product_margin_csv(self.salon))

    def test_explicit_csv_format_kwargs_matches_service(self):
        out = io.StringIO()
        call_command("export_product_margin", salon_id=self.salon.pk,
                     format="csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_product_margin_csv(self.salon))

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_product_margin", "--salon-id",
                     str(self.salon.pk), "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_product_margin_csv(self.salon))

    def test_json_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command("export_product_margin", salon_id=self.salon.pk,
                     format="json", stdout=out)
        rows = export_product_margin(self.salon)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(out.getvalue(), json.dumps(rows, indent=2) + "\n")

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_product_margin", "--salon-id",
                     str(self.salon.pk), "--format", "json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         export_product_margin(self.salon))

    def test_json_empty_salon_is_empty_list(self):
        out = io.StringIO()
        call_command("export_product_margin", salon_id=self.empty.pk,
                     format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(json.loads(out.getvalue()),
                         export_product_margin(self.empty))
        self.assertEqual(out.getvalue(), "[]\n")

    def test_json_composes_with_date_window(self):
        out = io.StringIO()
        call_command("export_product_margin", salon_id=self.salon.pk,
                     format="json", start_date="2026-10-03",
                     end_date="2026-10-03", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(rows, export_product_margin(
            self.salon, start_date=DAY, end_date=DAY))
        self.assertEqual(rows[0]["units_sold"], 2)
        self.assertEqual(rows[0]["sales_start_date"], "2026-10-03")
        self.assertEqual(rows[0]["sales_end_date"], "2026-10-03")

    def test_csv_composes_with_date_window(self):
        out = io.StringIO()
        call_command("export_product_margin", salon_id=self.salon.pk,
                     format="csv", start_date="2026-10-03",
                     end_date="2026-10-03", stdout=out)
        self.assertEqual(out.getvalue(), export_product_margin_csv(
            self.salon, start_date=DAY, end_date=DAY))

    def test_json_output_file_parses_and_equals_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "margin.json")
            call_command("export_product_margin", salon_id=self.salon.pk,
                         format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        rows = export_product_margin(self.salon)
        self.assertEqual(json.loads(text), rows)
        self.assertEqual(text, json.dumps(rows, indent=2) + "\n")
        self.assertEqual(out.getvalue(), "")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_product_margin", salon_id=self.salon.pk,
                         format="xml", stdout=io.StringIO())

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_product_margin", "--salon-id",
                         str(self.salon.pk), "--format", "xml",
                         stdout=io.StringIO())
