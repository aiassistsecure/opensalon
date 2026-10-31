"""Tests for the checkout export_void management command.

The command is a thin wrapper around
``checkout.void_export.export_voided_sales_csv``: these tests
pin that its stdout and file output match that service verbatim,
that it scopes to the requested salon, and that unknown salons,
bad dates, reversed ranges, service errors, and unwritable
output fail cleanly as ``CommandError``. Fixtures are tiny
synthetic records -- unit logic only.

These tests load the checkout command class explicitly via
``load_command_class("checkout", "export_void")`` and pass
that instance to ``call_command`` -- pinning this app's
command, not the global name resolution.
"""
import datetime
import io
import os
import tempfile
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command, load_command_class
from django.test import TestCase
from django.utils import timezone

from checkout.models import Sale, SaleItem
from checkout.void import void_sale
from checkout.void_export import export_voided_sales_csv
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)
NEXT = DAY + datetime.timedelta(days=1)


def _cmd():
    return load_command_class("checkout", "export_void")


def _stamp(day, hour=12):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, 0)),
        datetime.timezone.utc)


class ExportVoidCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")

    def _voided_sale(self, salon=None, price="85.00", day=DAY,
                     reason="entered in error"):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED,
            completed_at=_stamp(day))
        SaleItem.objects.create(
            sale=sale, kind="service", description="service",
            unit_price=Decimal(price), quantity=1)
        void_sale(sale, reason)
        Sale.objects.filter(pk=sale.pk).update(voided_at=_stamp(day))
        sale.refresh_from_db()
        return sale

    def test_stdout_matches_service_single_day(self):
        self._voided_sale()
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, date_from=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_voided_sales_csv(self.salon, DAY))

    def test_stdout_matches_service_with_string_args(self):
        self._voided_sale()
        self._voided_sale(day=NEXT)
        out = io.StringIO()
        call_command(
            _cmd(), "--salon-id", str(self.salon.pk),
            "--date-from", DAY.isoformat(), "--date-to", NEXT.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_voided_sales_csv(self.salon, DAY, NEXT))

    def test_stdout_matches_service_with_kwargs_range(self):
        self._voided_sale()
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk, date_from=DAY, date_to=NEXT,
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_voided_sales_csv(self.salon, DAY, NEXT))

    def test_salon_scoping_excludes_other_salons(self):
        self._voided_sale()
        self._voided_sale(salon=self.other)
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, date_from=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_voided_sales_csv(self.salon, DAY))
        self.assertNotEqual(
            out.getvalue(), export_voided_sales_csv(self.other, DAY))

    def test_output_file_matches_service(self):
        self._voided_sale()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "void.csv")
            call_command(
                _cmd(), salon_id=self.salon.pk, date_from=DAY,
                date_to=NEXT, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_voided_sales_csv(self.salon, DAY, NEXT))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), salon_id=self.salon.pk + 999, date_from=DAY,
                stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        self._voided_sale()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "no-such-dir", "void.csv")
            with self.assertRaises(CommandError):
                call_command(
                    _cmd(), salon_id=self.salon.pk, date_from=DAY,
                    output=path, stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), salon_id=self.salon.pk, date_from="not-a-date",
                stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), salon_id=self.salon.pk, date_from=NEXT,
                date_to=DAY, stdout=io.StringIO())

    def test_service_error_raises_command_error(self):
        with mock.patch(
            "checkout.management.commands.export_void."
            "export_voided_sales_csv",
            side_effect=ValueError("boom"),
        ):
            with self.assertRaises(CommandError):
                call_command(
                    _cmd(), salon_id=self.salon.pk, date_from=DAY,
                    stdout=io.StringIO())
