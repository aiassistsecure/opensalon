"""Tests for the export_tender_mix management command.

The command is a thin wrapper around
``checkout.tender_mix_export.export_tender_mix_csv``: these tests
pin that its stdout and file output match that service verbatim,
that it scopes to the requested salon, and that unknown salons,
missing/invalid dates, reversed ranges, and unwritable output
fail cleanly as ``CommandError``.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.models import Payment, Sale
from checkout.tender_mix_export import export_tender_mix_csv
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)
NEXT = DAY + datetime.timedelta(days=1)


def _stamp(day, hour=12):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, 0)),
        datetime.timezone.utc)


class ExportTenderMixCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self._payment(self.salon)
        self._payment(self.other)

    def _payment(self, salon):
        sale = Sale.objects.create(
            salon=salon, status=Sale.Status.COMPLETED,
            completed_at=_stamp(DAY))
        payment = Payment.objects.create(
            sale=sale, method=Payment.Method.CASH,
            amount=Decimal("85.00"), status=Payment.Status.COMPLETED)
        stamp = _stamp(DAY)
        Payment.objects.filter(pk=payment.pk).update(
            created_at=stamp, updated_at=stamp)
        payment.refresh_from_db()
        return payment

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_tender_mix", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_tender_mix_csv(self.salon, DAY, DAY))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_tender_mix", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", NEXT.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_tender_mix_csv(self.salon, DAY, NEXT))

    def test_salon_scoping(self):
        out = io.StringIO()
        call_command(
            "export_tender_mix", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        text = out.getvalue()
        self.assertEqual(
            text, export_tender_mix_csv(self.salon, DAY, DAY))
        self.assertNotEqual(
            text, export_tender_mix_csv(self.other, DAY, DAY))
        lines = text.strip().splitlines()
        # Header + one zero-filled-or-total row per tender method.
        self.assertEqual(len(lines), 3)
        for line in lines[1:]:
            self.assertTrue(line.startswith(f"{self.salon.pk},"))
        self.assertIn("cash,85.00,85.00,100.00,1", text)

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tender_mix.csv")
            call_command(
                "export_tender_mix", salon_id=self.salon.pk,
                start_date=DAY, end_date=NEXT, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_tender_mix_csv(self.salon, DAY, NEXT))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_tender_mix", salon_id=self.salon.pk + 999,
                start_date=DAY, end_date=DAY, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "missing-dir", "tender_mix.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_tender_mix", salon_id=self.salon.pk,
                    start_date=DAY, end_date=DAY, output=bad,
                    stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_tender_mix", salon_id=self.salon.pk,
                start_date="not-a-date", end_date=DAY,
                stdout=io.StringIO())

    def test_missing_dates_raise_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_tender_mix", salon_id=self.salon.pk,
                stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_tender_mix", salon_id=self.salon.pk,
                start_date=NEXT, end_date=DAY, stdout=io.StringIO())
