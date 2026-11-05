"""Tests for the catalog export_prior_product_sales command --format.

The command is a thin wrapper around
``catalog.prior_product_sales_export``: these tests pin that its
CSV stdout and file output match
``export_prior_product_sales_csv`` verbatim (byte-identical by
default and explicitly), that its JSON output parses to the dict
rows from ``export_prior_product_sales`` serialised with
``DjangoJSONEncoder`` (indent=2 + trailing newline) and composes
with the salon / date-window filters, and that unknown formats,
unknown salons and unwritable output fail cleanly.
"""
import io
import json
import os
import tempfile
from datetime import date, datetime, time, timedelta, timezone as dt_tz
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from catalog.models import Product
from catalog.prior_product_sales_export import (
    PRIOR_PRODUCT_SALES_FIELDNAMES,
    export_prior_product_sales,
    export_prior_product_sales_csv,
)
from checkout.models import Sale, SaleItem
from saloncore.models import Salon

DAY = date(2026, 10, 3)
PRIOR = DAY - timedelta(days=1)


def _expected_json(salon, **kwargs):
    rows = export_prior_product_sales(salon, **kwargs)
    return json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportPriorProductSalesFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.empty = Salon.objects.create(name="Empty Salon")
        self.alpha = Product.objects.create(
            salon=self.salon, name="Alpha", sku="A-1", barcode="111",
            price=Decimal("10.00"), cost_price=Decimal("6.00"))
        self.sell(self.alpha, 2, "10.00", on=PRIOR)
        self.sell(self.alpha, 3, "10.00", on=DAY)
        foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999", price=Decimal("1.00"),
            cost_price=Decimal("0.50"))
        self.sell(foreign, 9, "99.00", on=DAY, salon=self.other)

    def sell(self, product, quantity, unit_price, on, salon=None):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.PRODUCT, product=product,
            description=product.name, quantity=quantity,
            unit_price=Decimal(unit_price))
        when = datetime.combine(on, time(12), tzinfo=dt_tz.utc)
        Sale.objects.filter(pk=sale.pk).update(
            completed_at=when, created_at=when)
        return sale

    def _call(self, out, **kwargs):
        kwargs.setdefault("salon_id", self.salon.pk)
        kwargs.setdefault("start_date", DAY)
        kwargs.setdefault("end_date", DAY)
        call_command("export_prior_product_sales", stdout=out, **kwargs)

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        self._call(out)
        self.assertEqual(out.getvalue(), export_prior_product_sales_csv(
            self.salon, start_date=DAY, end_date=DAY))
        self.assertEqual(out.getvalue().splitlines()[0].split(","),
                         PRIOR_PRODUCT_SALES_FIELDNAMES)

    def test_explicit_csv_format_kwargs_matches_service(self):
        out = io.StringIO()
        self._call(out, format="csv")
        self.assertEqual(out.getvalue(), export_prior_product_sales_csv(
            self.salon, start_date=DAY, end_date=DAY))

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_prior_product_sales", "--salon-id",
                     str(self.salon.pk), "--start-date", "2026-10-03",
                     "--end-date", "2026-10-03", "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), export_prior_product_sales_csv(
            self.salon, start_date=DAY, end_date=DAY))

    def test_json_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        self._call(out, format="json")
        rows = export_prior_product_sales(
            self.salon, start_date=DAY, end_date=DAY)
        self.assertEqual(json.loads(out.getvalue()), _parsed(rows))
        self.assertEqual(out.getvalue(), _expected_json(
            self.salon, start_date=DAY, end_date=DAY))
        self.assertIn("Alpha", out.getvalue())
        self.assertNotIn("Foreign", out.getvalue())

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_prior_product_sales", "--salon-id",
                     str(self.salon.pk), "--start-date", "2026-10-03",
                     "--end-date", "2026-10-03", "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(
            self.salon, start_date=DAY, end_date=DAY))

    def test_json_composes_with_date_window(self):
        out = io.StringIO()
        self._call(out, format="json")
        rows = json.loads(out.getvalue())
        self.assertEqual(rows[0]["current_start_date"], "2026-10-03")
        self.assertEqual(rows[0]["prior_start_date"], "2026-10-02")
        alpha = next(r for r in rows if r["product_name"] == "Alpha")
        self.assertEqual(alpha["current_units_sold"], 3)
        self.assertEqual(alpha["prior_units_sold"], 2)

    def test_csv_composes_with_date_window(self):
        out = io.StringIO()
        self._call(out, format="csv")
        self.assertEqual(out.getvalue(), export_prior_product_sales_csv(
            self.salon, start_date=DAY, end_date=DAY))

    def test_json_empty_salon_is_total_row_only(self):
        out = io.StringIO()
        self._call(out, salon_id=self.empty.pk, format="json")
        rows = export_prior_product_sales(
            self.empty, start_date=DAY, end_date=DAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(out.getvalue()), _parsed(rows))
        self.assertEqual(out.getvalue(), _expected_json(
            self.empty, start_date=DAY, end_date=DAY))

    def test_json_scopes_to_salon(self):
        out = io.StringIO()
        self._call(out, salon_id=self.other.pk, format="json")
        self.assertEqual(out.getvalue(), _expected_json(
            self.other, start_date=DAY, end_date=DAY))
        self.assertIn("Foreign", out.getvalue())

    def test_json_output_file_parses_and_equals_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior-sales.json")
            self._call(out, format="json", output=path)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, _expected_json(
            self.salon, start_date=DAY, end_date=DAY))
        self.assertEqual(json.loads(text), _parsed(
            export_prior_product_sales(
                self.salon, start_date=DAY, end_date=DAY)))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior-sales.csv")
            self._call(out, output=path)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, export_prior_product_sales_csv(
            self.salon, start_date=DAY, end_date=DAY))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(io.StringIO(), format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_prior_product_sales", "--salon-id",
                         str(self.salon.pk), "--start-date",
                         "2026-10-03", "--end-date", "2026-10-03",
                         "--format", "xml", stdout=io.StringIO())

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(io.StringIO(), salon_id=999999, format="json")

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.json")
            with self.assertRaises(CommandError):
                self._call(io.StringIO(), format="json", output=path)
