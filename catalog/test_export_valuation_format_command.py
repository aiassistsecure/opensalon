"""Tests for the catalog export_valuation command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_stock_valuation_csv``
service), that JSON parses to the dict rows from the new twin
``export_stock_valuation`` -- the same rows the CSV is built
from -- serialised with ``DjangoJSONEncoder`` (indent=2 +
trailing newline), and that unknown formats fail cleanly.
"""
import csv
import io
import json
import os
import tempfile
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.valuation_export import (
    VALUATION_FIELDNAMES,
    export_stock_valuation,
    export_stock_valuation_csv,
)
from saloncore.models import Salon


def _expected_json(salon):
    return json.dumps(export_stock_valuation(salon), indent=2,
                      cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportValuationFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.empty = Salon.objects.create(name="Empty Salon")
        self.shampoo = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        StockMovement.objects.create(
            product=self.shampoo, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=6)
        self.serum = Product.objects.create(
            salon=self.salon, name="Serum", sku="SE-002",
            barcode="222333444555", price=Decimal("19.99"))
        foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999", price=Decimal("1.00"))
        StockMovement.objects.create(
            product=foreign, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=5)

    def _pinned_csv(self):
        return (
            ",".join(VALUATION_FIELDNAMES) + "\n"
            f"{self.shampoo.pk},Shampoo,SH-001,012345678905,6,"
            "10.00,60.00\n"
            f"{self.serum.pk},Serum,SE-002,222333444555,0,"
            "19.99,0.00\n"
        )

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(export_stock_valuation_csv(self.salon),
                         self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command("export_valuation", salon_id=self.salon.pk,
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())
        self.assertEqual(out.getvalue(),
                         export_stock_valuation_csv(self.salon))

    def test_explicit_csv_format_kwargs_matches_service(self):
        out = io.StringIO()
        call_command("export_valuation", salon_id=self.salon.pk,
                     format="csv", stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_valuation", "--salon-id",
                     str(self.salon.pk), "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_stock_valuation(self.salon)
        parsed = list(csv.DictReader(io.StringIO(
            export_stock_valuation_csv(self.salon))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in rows],
            parsed)
        self.assertEqual([list(row) for row in rows],
                         [VALUATION_FIELDNAMES] * len(rows))
        self.assertEqual(rows[0]["unit_price"], "10.00")
        self.assertEqual(rows[0]["retail_value"], "60.00")
        self.assertIsInstance(rows[0]["on_hand"], int)

    def test_json_parses_and_equals_dict_twin(self):
        out = io.StringIO()
        call_command("export_valuation", salon_id=self.salon.pk,
                     format="json", stdout=out)
        rows = export_stock_valuation(self.salon)
        self.assertEqual(json.loads(out.getvalue()), _parsed(rows))
        self.assertEqual(out.getvalue(), _expected_json(self.salon))
        self.assertIn("Shampoo", out.getvalue())
        self.assertNotIn("Foreign", out.getvalue())

    def test_json_rows_equal_csv_rows(self):
        out = io.StringIO()
        call_command("export_valuation", salon_id=self.salon.pk,
                     format="json", stdout=out)
        json_rows = json.loads(out.getvalue())
        csv_rows = list(csv.DictReader(io.StringIO(
            export_stock_valuation_csv(self.salon))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_valuation", "--salon-id",
                     str(self.salon.pk), "--format", "json", stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon))

    def test_json_output_file(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "valuation.json")
            call_command("export_valuation", salon_id=self.salon.pk,
                         format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, _expected_json(self.salon))
        self.assertEqual(json.loads(text),
                         _parsed(export_stock_valuation(self.salon)))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "valuation.csv")
            call_command("export_valuation", salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_salon_json_and_csv(self):
        out = io.StringIO()
        call_command("export_valuation", salon_id=self.empty.pk,
                     format="json", stdout=out)
        self.assertEqual(out.getvalue(), "[]\n")
        self.assertEqual(export_stock_valuation(self.empty), [])
        out = io.StringIO()
        call_command("export_valuation", salon_id=self.empty.pk,
                     stdout=out)
        self.assertEqual(out.getvalue(),
                         ",".join(VALUATION_FIELDNAMES) + "\n")

    def test_json_scopes_to_salon(self):
        out = io.StringIO()
        call_command("export_valuation", salon_id=self.other.pk,
                     format="json", stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.other))
        self.assertIn("Foreign", out.getvalue())

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_valuation", salon_id=self.salon.pk,
                         format="xml", stdout=io.StringIO())

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_valuation", "--salon-id",
                         str(self.salon.pk), "--format", "xml",
                         stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_valuation", salon_id=999999,
                         format="json", stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.json")
            with self.assertRaises(CommandError):
                call_command("export_valuation",
                             salon_id=self.salon.pk, format="json",
                             output=path, stdout=io.StringIO())
