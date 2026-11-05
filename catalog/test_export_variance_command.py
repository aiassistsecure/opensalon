"""Tests for the export_variance management command.

The command is a thin wrapper around
``catalog.variance_export``; these tests check delegation
(stdout/file match the service output verbatim, as CSV by
default and as JSON via the dict-row service), salon scoping,
and clean failure for an unknown format, an unknown salon, a
foreign counted product, and an unwritable output.
"""
import csv
import io
import json
import os
import tempfile
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.variance_export import (
    VARIANCE_FIELDNAMES,
    export_stocktake_variance,
    export_stocktake_variance_csv,
)
from saloncore.models import Salon


class ExportVarianceCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.shampoo = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        self.move(self.shampoo, 10)
        self.serum = Product.objects.create(
            salon=self.salon, name="Serum", sku="SE-002",
            barcode="222333444555", price=Decimal("19.99"))
        self.move(self.serum, 3)
        self.foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999", price=Decimal("1.00"))
        self.move(self.foreign, 9)
        self.counts = {self.shampoo.pk: 6, self.serum.pk: 5}

    def move(self, product, delta):
        return StockMovement.objects.create(
            product=product, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=delta)

    def expected_text(self, salon, counts):
        return export_stocktake_variance_csv(salon, counts)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_variance", salon_id=self.salon.pk,
                     counts=self.counts, stdout=out)
        text = out.getvalue()
        self.assertEqual(text, self.expected_text(self.salon, self.counts))
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(list(rows[0].keys()), VARIANCE_FIELDNAMES)
        self.assertEqual(sorted(r["product_name"] for r in rows),
                         ["Serum", "Shampoo"])
        by_name = {r["product_name"]: r for r in rows}
        self.assertEqual(by_name["Shampoo"]["difference"], "-4")
        self.assertEqual(by_name["Shampoo"]["retail_value_impact"], "-40.00")
        self.assertNotIn("Foreign", text)

    def test_count_flags_match_service(self):
        out = io.StringIO()
        call_command(
            "export_variance", "--salon-id", str(self.salon.pk),
            "--count", f"{self.shampoo.pk}=6",
            "--count", f"{self.serum.pk}=5", stdout=out)
        self.assertEqual(
            out.getvalue(), self.expected_text(self.salon, self.counts))

    def test_no_counts_exports_header_only(self):
        out = io.StringIO()
        call_command("export_variance", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(),
                         self.expected_text(self.salon, {}))
        self.assertEqual(out.getvalue(),
                         ",".join(VARIANCE_FIELDNAMES) + "\n")

    def test_salon_scoping_foreign_count_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_variance", salon_id=self.salon.pk,
                         counts={self.foreign.pk: 1},
                         stdout=io.StringIO())

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "variance.csv")
            call_command("export_variance", salon_id=self.salon.pk,
                         counts=self.counts, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, self.expected_text(self.salon, self.counts))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_variance", salon_id=999999,
                         stdout=io.StringIO())

    def test_default_is_csv_byte_identical(self):
        default_out = io.StringIO()
        call_command("export_variance", salon_id=self.salon.pk,
                     counts=self.counts, stdout=default_out)
        csv_out = io.StringIO()
        call_command("export_variance", salon_id=self.salon.pk,
                     counts=self.counts, format="csv", stdout=csv_out)
        self.assertEqual(default_out.getvalue(), csv_out.getvalue())
        self.assertEqual(
            default_out.getvalue(),
            self.expected_text(self.salon, self.counts))

    def test_explicit_csv_via_cli_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_variance", "--salon-id", str(self.salon.pk),
            "--count", f"{self.shampoo.pk}=6",
            "--count", f"{self.serum.pk}=5", "--format", "csv",
            stdout=out)
        self.assertEqual(
            out.getvalue(), self.expected_text(self.salon, self.counts))

    def test_json_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command("export_variance", salon_id=self.salon.pk,
                     counts=self.counts, format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_stocktake_variance(self.salon, self.counts))
        self.assertEqual(
            out.getvalue(),
            json.dumps(
                export_stocktake_variance(self.salon, self.counts),
                indent=2, cls=DjangoJSONEncoder) + "\n")
        self.assertNotIn("Foreign", out.getvalue())

    def test_json_via_cli_matches_dict_service(self):
        out = io.StringIO()
        call_command(
            "export_variance", "--salon-id", str(self.salon.pk),
            "--count", f"{self.shampoo.pk}=6",
            "--count", f"{self.serum.pk}=5", "--format", "json",
            stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_stocktake_variance(self.salon, self.counts))

    def test_json_no_counts_is_empty_list(self):
        out = io.StringIO()
        call_command("export_variance", salon_id=self.salon.pk,
                     format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(
            json.loads(out.getvalue()),
            export_stocktake_variance(self.salon, {}))

    def test_json_delegates_to_dict_service_verbatim(self):
        with mock.patch(
            "catalog.management.commands.export_variance"
            ".export_stocktake_variance",
            wraps=export_stocktake_variance,
        ) as spy:
            call_command("export_variance", salon_id=self.salon.pk,
                         counts=self.counts, format="json",
                         stdout=io.StringIO())
        spy.assert_called_once_with(self.salon, self.counts)

    def test_json_output_file_parses_and_equals_dict_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "variance.json")
            call_command("export_variance", salon_id=self.salon.pk,
                         counts=self.counts, format="json", output=path,
                         stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written),
            export_stocktake_variance(self.salon, self.counts))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_variance", salon_id=self.salon.pk,
                         counts=self.counts, format="xml",
                         stdout=io.StringIO())

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_variance", "--salon-id", str(self.salon.pk),
                "--format", "xml", stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "variance.csv")
            with self.assertRaises(CommandError):
                call_command("export_variance", salon_id=self.salon.pk,
                             counts=self.counts, output=path,
                             stdout=io.StringIO())
