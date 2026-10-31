"""Tests for the checkout export_search management command.

The command is a thin wrapper around
``checkout.search_export.export_search_sales_csv``: these tests
pin that its stdout and file output match that service verbatim,
that it scopes to the requested salon, and that unknown salons,
bad dates, reversed ranges, bad min-total, and unwritable
output fail cleanly as ``CommandError``. Fixtures are tiny
synthetic records -- unit logic only.

Note: ``bookings`` already owns the global ``export_search``
command name, so these tests load the checkout command class
explicitly via ``load_command_class("checkout", "export_search")``
and pass that instance to ``call_command`` -- pinning this app's
command, not the global name resolution.
"""
import datetime
import io
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command, load_command_class
from django.test import TestCase
from django.utils import timezone

from checkout.models import Sale, SaleItem
from checkout.search_export import export_search_sales_csv
from clients.models import Client
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)
NEXT = DAY + datetime.timedelta(days=1)


def _cmd():
    return load_command_class("checkout", "export_search")


def _stamp(day, hour=12):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, 0)),
        datetime.timezone.utc)


class ExportSearchCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.ana = Client.objects.create(
            salon=self.salon, first_name="Ana", last_name="Lopez")

    def _sale(self, salon=None, client=None, price="85.00", day=DAY,
              status=Sale.Status.COMPLETED):
        sale = Sale.objects.create(
            salon=salon or self.salon, client=client, status=status)
        SaleItem.objects.create(
            sale=sale, kind="service", description="service",
            unit_price=Decimal(price), quantity=1)
        stamp = _stamp(day)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        sale.refresh_from_db()
        return sale

    def test_stdout_matches_service(self):
        self._sale(client=self.ana)
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_search_sales_csv(self.salon))

    def test_stdout_matches_service_with_string_args(self):
        self._sale(client=self.ana)
        self._sale(day=NEXT)
        out = io.StringIO()
        call_command(
            _cmd(), "--salon-id", str(self.salon.pk),
            "--client-name", "lopez",
            "--date-from", DAY.isoformat(), "--date-to", DAY.isoformat(),
            "--min-total", "10.00", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_search_sales_csv(
                self.salon, client_name="lopez", date_from=DAY,
                date_to=DAY, min_total="10.00"))

    def test_stdout_matches_service_with_kwargs_filters(self):
        self._sale(client=self.ana)
        voided = self._sale(status=Sale.Status.VOIDED)
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk, include_voided=True, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_search_sales_csv(self.salon, include_voided=True))
        self.assertIn(str(voided.pk), out.getvalue())

    def test_stdout_excludes_voided_by_default(self):
        self._sale(client=self.ana)
        self._sale(status=Sale.Status.VOIDED)
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_search_sales_csv(self.salon))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_salon_scoping_excludes_other_salons(self):
        self._sale()
        self._sale(salon=self.other)
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_search_sales_csv(self.salon))
        self.assertNotEqual(
            out.getvalue(), export_search_sales_csv(self.other))

    def test_output_file_matches_service(self):
        self._sale(client=self.ana)
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "search.csv")
            call_command(
                _cmd(), salon_id=self.salon.pk, client_name="ana",
                output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written,
            export_search_sales_csv(self.salon, client_name="ana"))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), salon_id=self.salon.pk + 999, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        self._sale()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "no-such-dir", "search.csv")
            with self.assertRaises(CommandError):
                call_command(
                    _cmd(), salon_id=self.salon.pk, output=path,
                    stdout=io.StringIO())

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

    def test_invalid_min_total_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), salon_id=self.salon.pk, min_total="not-a-number",
                stdout=io.StringIO())
