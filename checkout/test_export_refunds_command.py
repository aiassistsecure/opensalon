"""Tests for the export_refunds management command.

The command is a thin wrapper around
``checkout.refund_export.export_refunds_csv``: these tests pin
that its stdout and file output match that service verbatim,
that it scopes to the requested salon, and that unknown salons,
bad dates, reversed ranges, and unwritable output fail cleanly
as ``CommandError``. Fixtures are tiny synthetic records --
unit logic only.
"""
import datetime
import io
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.models import Payment, Refund, Sale
from checkout.refund_export import export_refunds_csv
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)
NEXT = DAY + datetime.timedelta(days=1)


def _stamp(day, hour=12):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, 0)),
        datetime.timezone.utc)


class ExportRefundsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")

    def _refund(self, salon=None, day=DAY):
        salon = salon or self.salon
        sale = Sale.objects.create(
            salon=salon, status=Sale.Status.COMPLETED,
            completed_at=_stamp(day))
        refund = Refund.objects.create(
            sale=sale, amount=Decimal("20.00"), reason="Changed mind",
            tender=Payment.Method.CASH)
        stamp = _stamp(day)
        Refund.objects.filter(pk=refund.pk).update(created_at=stamp)
        refund.refresh_from_db()
        return refund

    def test_stdout_matches_service(self):
        self._refund()
        out = io.StringIO()
        call_command(
            "export_refunds", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_refunds_csv(self.salon, DAY, DAY))

    def test_stdout_matches_service_with_string_date_args(self):
        self._refund()
        out = io.StringIO()
        call_command(
            "export_refunds", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", NEXT.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(), export_refunds_csv(self.salon, DAY, NEXT))

    def test_stdout_single_day_when_end_date_omitted(self):
        self._refund()
        out = io.StringIO()
        call_command(
            "export_refunds", salon_id=self.salon.pk,
            start_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_refunds_csv(self.salon, DAY, None))
        self.assertEqual(
            out.getvalue(), export_refunds_csv(self.salon, DAY))

    def test_salon_scoping_excludes_other_salons(self):
        self._refund()
        self._refund(salon=self.other)
        out = io.StringIO()
        call_command(
            "export_refunds", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        text = out.getvalue()
        self.assertEqual(text, export_refunds_csv(self.salon, DAY, DAY))
        self.assertNotEqual(text, export_refunds_csv(self.other, DAY, DAY))
        self.assertEqual(len(text.strip().splitlines()), 2)

    def test_output_file_matches_service(self):
        self._refund()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "refunds.csv")
            call_command(
                "export_refunds", salon_id=self.salon.pk,
                start_date=DAY, end_date=NEXT, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_refunds_csv(self.salon, DAY, NEXT))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_refunds", salon_id=self.salon.pk + 999,
                start_date=DAY, end_date=DAY, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        self._refund()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "no-such-dir", "refunds.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_refunds", salon_id=self.salon.pk,
                    start_date=DAY, end_date=DAY, output=path,
                    stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_refunds", salon_id=self.salon.pk,
                start_date="not-a-date", end_date=DAY,
                stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_refunds", salon_id=self.salon.pk,
                start_date=NEXT, end_date=DAY, stdout=io.StringIO())
