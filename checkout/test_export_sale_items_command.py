"""Tests for the export_sale_items management command.

The command is a thin wrapper around
``checkout.sale_item_export.export_sale_items_csv``: these
tests pin that its stdout and file output match that service
verbatim, that it scopes to the requested salon, and that
unknown salons, bad dates, reversed ranges, and unwritable
output fail cleanly as ``CommandError``.
"""
import datetime
import io
import json
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase
from django.utils import timezone

from checkout.models import Sale, SaleItem
from checkout.sale_item_export import (
    export_sale_items, export_sale_items_csv)
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)
NEXT = DAY + datetime.timedelta(days=1)


def _stamp(day, hour=12):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, 0)),
        datetime.timezone.utc)


class ExportSaleItemsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Item Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")

    def _item(self, salon=None, day=DAY, kind=SaleItem.Kind.SERVICE,
              sale=None):
        if sale is None:
            sale = Sale.objects.create(
                salon=salon or self.salon, status=Sale.Status.COMPLETED)
            Sale.objects.filter(pk=sale.pk).update(
                created_at=_stamp(day))
        return SaleItem.objects.create(
            sale=sale, kind=kind, description="Haircut",
            quantity=1, unit_price=Decimal("85.00"))

    def test_stdout_matches_service_no_range(self):
        self._item()
        out = io.StringIO()
        call_command("export_sale_items", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_sale_items_csv(self.salon))

    def test_stdout_matches_service_with_range(self):
        self._item()
        self._item(day=NEXT + datetime.timedelta(days=5))
        out = io.StringIO()
        call_command(
            "export_sale_items", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", NEXT.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(), export_sale_items_csv(self.salon, DAY, NEXT))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)



    def test_output_file_matches_service(self):
        self._item()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sale_items.csv")
            call_command(
                "export_sale_items", salon_id=self.salon.pk,
                output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(written, export_sale_items_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_sale_id_filters_to_one_sale(self):
        first = self._item()
        self._item()
        out = io.StringIO()
        call_command(
            "export_sale_items", salon_id=self.salon.pk,
            sale_id=first.sale_id, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sale_items_csv(self.salon, sale=first.sale))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_sale_id_via_cli_flag(self):
        first = self._item()
        out = io.StringIO()
        call_command(
            "export_sale_items", "--salon-id", str(self.salon.pk),
            "--sale-id", str(first.sale_id), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sale_items_csv(self.salon, sale=first.sale))

    def test_no_sale_id_is_salon_wide_default(self):
        self._item()
        out = io.StringIO()
        call_command(
            "export_sale_items", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_sale_items_csv(self.salon))
        self.assertEqual(
            out.getvalue(),
            export_sale_items_csv(self.salon, sale=None))

    def test_kind_filters_to_one_kind(self):
        service = self._item()
        self._item(kind=SaleItem.Kind.PRODUCT, sale=service.sale)
        self._item(kind=SaleItem.Kind.SERIES, sale=service.sale)
        out = io.StringIO()
        call_command(
            "export_sale_items", salon_id=self.salon.pk,
            kind="product", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sale_items_csv(self.salon, kind="product"))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_kind_via_cli_flag(self):
        self._item()
        out = io.StringIO()
        call_command(
            "export_sale_items", "--salon-id", str(self.salon.pk),
            "--kind", "service", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sale_items_csv(self.salon, kind="service"))

    def test_no_kind_is_all_kinds_default(self):
        service = self._item()
        self._item(kind=SaleItem.Kind.PRODUCT, sale=service.sale)
        out = io.StringIO()
        call_command(
            "export_sale_items", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_sale_items_csv(self.salon))
        self.assertEqual(
            out.getvalue(),
            export_sale_items_csv(self.salon, kind=None))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 3)

    def test_kind_composes_with_sale_and_range(self):
        service = self._item()
        product = self._item(
            kind=SaleItem.Kind.PRODUCT, sale=service.sale)
        self._item()
        out = io.StringIO()
        call_command(
            "export_sale_items", salon_id=self.salon.pk,
            sale_id=service.sale_id, kind="product",
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sale_items_csv(
                self.salon, DAY, DAY, sale=service.sale, kind="product"))
        self.assertIn(str(product.pk), out.getvalue())
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_default_is_csv_byte_identical(self):
        self._item()
        default_out = io.StringIO()
        call_command(
            "export_sale_items", salon_id=self.salon.pk,
            stdout=default_out)
        csv_out = io.StringIO()
        call_command(
            "export_sale_items", salon_id=self.salon.pk,
            format="csv", stdout=csv_out)
        self.assertEqual(default_out.getvalue(), csv_out.getvalue())
        self.assertEqual(
            default_out.getvalue(), export_sale_items_csv(self.salon))

    def test_explicit_csv_via_cli_matches_service(self):
        self._item()
        out = io.StringIO()
        call_command(
            "export_sale_items", "--salon-id", str(self.salon.pk),
            "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), export_sale_items_csv(self.salon))

    def test_json_parses_and_equals_dict_service_rows(self):
        self._item()
        out = io.StringIO()
        call_command(
            "export_sale_items", salon_id=self.salon.pk,
            format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()), export_sale_items(self.salon))
        self.assertEqual(
            out.getvalue(),
            json.dumps(
                export_sale_items(self.salon),
                indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_via_cli_with_filters_matches_dict_service(self):
        service = self._item()
        self._item(kind=SaleItem.Kind.PRODUCT, sale=service.sale)
        self._item()
        out = io.StringIO()
        call_command(
            "export_sale_items", "--salon-id", str(self.salon.pk),
            "--sale-id", str(service.sale_id), "--kind", "product",
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_sale_items(
                self.salon, DAY, DAY, sale=service.sale, kind="product"))

    def test_json_output_file_parses_and_equals_dict_service(self):
        self._item()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sale_items.json")
            call_command(
                "export_sale_items", salon_id=self.salon.pk,
                format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written), export_sale_items(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_sale_items", salon_id=self.salon.pk,
                format="xml", stdout=io.StringIO())

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_sale_items", "--salon-id", str(self.salon.pk),
                "--format", "xml", stdout=io.StringIO())

    def test_unknown_sale_id_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_sale_items", salon_id=self.salon.pk,
                sale_id=999999, stdout=io.StringIO())

    def test_sale_from_other_salon_raises_command_error(self):
        theirs = self._item(salon=self.other)
        with self.assertRaises(CommandError):
            call_command(
                "export_sale_items", salon_id=self.salon.pk,
                sale_id=theirs.sale_id, stdout=io.StringIO())

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_sale_items", salon_id=self.salon.pk + 999,
                stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        self._item()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "no-such-dir", "sale_items.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_sale_items", salon_id=self.salon.pk,
                    output=path, stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_sale_items", salon_id=self.salon.pk,
                start_date="not-a-date", stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_sale_items", salon_id=self.salon.pk,
                start_date=NEXT, end_date=DAY, stdout=io.StringIO())

    def test_end_date_without_start_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_sale_items", salon_id=self.salon.pk,
                end_date=DAY, stdout=io.StringIO())
