"""Tests for the export_adjust management command.

The command is a thin wrapper around
``catalog.adjust_export.export_stock_adjustments_csv``; these tests
check delegation (stdout/file match the service output verbatim,
as CSV), salon scoping, date filtering, and clean failure for an
unknown salon, an invalid range bound, and an unwritable output.
"""
import csv
import io
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from catalog.adjust_export import (
    ADJUST_FIELDNAMES,
    export_stock_adjustments,
    export_stock_adjustments_csv,
)
from catalog.models import Product, StockMovement
from saloncore.models import Salon


class ExportAdjustCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.day = date(2026, 10, 3)
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        self.move(self.product, -2, note="Damaged bottles", on=self.day)
        self.move(self.product, 10, kind=StockMovement.Kind.RECEIVE,
                  on=self.day)
        self.move(self.product, 5, note="Recount",
                  on=self.day + timedelta(days=1))
        foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999", price=Decimal("1.00"))
        self.move(foreign, 9, note="Foreign recount", on=self.day)

    def move(self, product, delta, kind=StockMovement.Kind.ADJUSTMENT,
             note="", on=None):
        movement = StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta, note=note)
        if on is not None:
            moment = timezone.make_aware(
                datetime(on.year, on.month, on.day, 12, 0))
            StockMovement.objects.filter(pk=movement.pk).update(
                created_at=moment)
        return movement

    def expected_text(self, *args, **kwargs):
        return export_stock_adjustments_csv(*args, **kwargs)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_adjust", salon_id=self.salon.pk, stdout=out)
        text = out.getvalue()
        self.assertEqual(text, self.expected_text(self.salon))
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(list(rows[0].keys()), ADJUST_FIELDNAMES)
        self.assertEqual([r["quantity_delta"] for r in rows], ["-2", "5"])
        self.assertEqual([r["note"] for r in rows],
                         ["Damaged bottles", "Recount"])
        self.assertNotIn("Foreign", text)

    def test_date_range_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_adjust", "--salon-id", str(self.salon.pk),
            "--start-date", self.day.isoformat(),
            "--end-date", self.day.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            self.expected_text(self.salon, start=self.day, end=self.day))
        rows = list(csv.DictReader(io.StringIO(out.getvalue())))
        self.assertEqual([r["quantity_delta"] for r in rows], ["-2"])
        after = self.day + timedelta(days=30)
        out = io.StringIO()
        call_command("export_adjust", salon_id=self.salon.pk,
                     start_date=after, end_date=after, stdout=out)
        self.assertEqual(
            out.getvalue(),
            ",".join(ADJUST_FIELDNAMES) + "\n")

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "adjust.csv")
            call_command("export_adjust", salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, self.expected_text(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_adjust", salon_id=999999,
                         stdout=io.StringIO())

    def test_invalid_bound_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_adjust", salon_id=self.salon.pk,
                         start_date="not-a-date", stdout=io.StringIO())

    def make_conditioner(self):
        conditioner = Product.objects.create(
            salon=self.salon, name="Conditioner", sku="CO-002",
            barcode="222", price=Decimal("12.00"))
        self.move(conditioner, 6, note="Recount", on=self.day)
        return conditioner

    def test_product_id_flag_scopes_csv_to_that_product(self):
        conditioner = self.make_conditioner()
        out = io.StringIO()
        call_command(
            "export_adjust", "--salon-id", str(self.salon.pk),
            "--product-id", str(conditioner.pk), stdout=out)
        text = out.getvalue()
        self.assertEqual(
            text, self.expected_text(self.salon, product=conditioner))
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual([r["product_name"] for r in rows],
                         ["Conditioner"])
        self.assertNotIn("Shampoo", text)

    def test_product_id_kwarg_scopes_csv_to_that_product(self):
        conditioner = self.make_conditioner()
        out = io.StringIO()
        call_command("export_adjust", salon_id=self.salon.pk,
                     product_id=conditioner.pk, stdout=out)
        self.assertEqual(
            out.getvalue(),
            self.expected_text(self.salon, product=conditioner))
        self.assertNotIn("Shampoo", out.getvalue())

    def test_no_product_flag_is_salon_wide_as_before(self):
        self.make_conditioner()
        out = io.StringIO()
        call_command("export_adjust", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), self.expected_text(self.salon))

    def test_unknown_product_id_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_adjust", salon_id=self.salon.pk,
                         product_id=999999, stdout=io.StringIO())

    def test_other_salon_product_id_raises_command_error(self):
        foreign = Product.objects.get(salon=self.other, name="Foreign")
        with self.assertRaises(CommandError):
            call_command("export_adjust", salon_id=self.salon.pk,
                         product_id=foreign.pk, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "adjust.csv")
            with self.assertRaises(CommandError):
                call_command("export_adjust", salon_id=self.salon.pk,
                             output=path, stdout=io.StringIO())


class ExportAdjustFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.empty = Salon.objects.create(name="Empty Salon")
        self.day = date(2026, 10, 3)
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        self.move(self.product, -2, note="Damaged bottles", on=self.day)
        self.move(self.product, 5, note="Recount",
                  on=self.day + timedelta(days=1))

    def move(self, product, delta, kind=StockMovement.Kind.ADJUSTMENT,
             note="", on=None):
        movement = StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta, note=note)
        if on is not None:
            moment = timezone.make_aware(
                datetime(on.year, on.month, on.day, 12, 0))
            StockMovement.objects.filter(pk=movement.pk).update(
                created_at=moment)
        return movement

    def rows(self, *args, **kwargs):
        return export_stock_adjustments(*args, **kwargs)

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command("export_adjust", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(
            out.getvalue(), export_stock_adjustments_csv(self.salon))

    def test_explicit_csv_format_kwargs_matches_service(self):
        out = io.StringIO()
        call_command("export_adjust", salon_id=self.salon.pk,
                     format="csv", stdout=out)
        self.assertEqual(
            out.getvalue(), export_stock_adjustments_csv(self.salon))

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command(
            "export_adjust", "--salon-id", str(self.salon.pk),
            "--format", "csv", stdout=out)
        self.assertEqual(
            out.getvalue(), export_stock_adjustments_csv(self.salon))

    def test_json_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command("export_adjust", salon_id=self.salon.pk,
                     format="json", stdout=out)
        rows = self.rows(self.salon)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(out.getvalue(), json.dumps(rows, indent=2) + "\n")

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(
            "export_adjust", "--salon-id", str(self.salon.pk),
            "--format", "json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), self.rows(self.salon))

    def test_json_empty_salon_is_empty_list(self):
        out = io.StringIO()
        call_command("export_adjust", salon_id=self.empty.pk,
                     format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(out.getvalue(), "[]\n")

    def test_json_composes_with_date_window(self):
        out = io.StringIO()
        call_command("export_adjust", salon_id=self.salon.pk,
                     start_date=self.day, end_date=self.day,
                     format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(
            rows, self.rows(self.salon, start=self.day, end=self.day))
        self.assertEqual([r["quantity_delta"] for r in rows], [-2])

    def test_json_composes_with_product_filter(self):
        conditioner = Product.objects.create(
            salon=self.salon, name="Conditioner", sku="CO-002",
            barcode="222", price=Decimal("12.00"))
        self.move(conditioner, 6, note="Recount", on=self.day)
        out = io.StringIO()
        call_command("export_adjust", salon_id=self.salon.pk,
                     product_id=conditioner.pk, format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(
            rows, self.rows(self.salon, product=conditioner))
        self.assertEqual([r["product_name"] for r in rows],
                         ["Conditioner"])

    def test_csv_composes_with_date_window(self):
        out = io.StringIO()
        call_command("export_adjust", salon_id=self.salon.pk,
                     start_date=self.day, end_date=self.day,
                     format="csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_stock_adjustments_csv(
                self.salon, start=self.day, end=self.day))

    def test_json_output_file_parses_and_equals_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "adjust.json")
            call_command("export_adjust", salon_id=self.salon.pk,
                         format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        rows = self.rows(self.salon)
        self.assertEqual(json.loads(text), rows)
        self.assertEqual(text, json.dumps(rows, indent=2) + "\n")
        self.assertEqual(out.getvalue(), "")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_adjust", salon_id=self.salon.pk,
                         format="xml", stdout=io.StringIO())

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command(
                "export_adjust", "--salon-id", str(self.salon.pk),
                "--format", "xml", stdout=io.StringIO())
