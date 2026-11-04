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
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.models import Sale, SaleItem
from checkout.sale_item_export import export_sale_items_csv
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

    def _item(self, salon=None, day=DAY):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED)
        Sale.objects.filter(pk=sale.pk).update(created_at=_stamp(day))
        return SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, description="Haircut",
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
