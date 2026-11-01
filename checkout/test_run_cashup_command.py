"""Tests for the run_cashup management command.

The command is a thin wrapper around
``checkout.cashup.run_cashup``: these tests pin that it creates
a cashup through that service, and that unknown salons and bad
datetimes fail cleanly as ``CommandError``. Fixtures are tiny
synthetic records -- unit logic only.
"""
import datetime
import io
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.models import Cashup, Payment, Sale, SaleItem
from saloncore.models import Salon


class RunCashupCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        now = timezone.now()
        self.since = now - datetime.timedelta(hours=1)
        self.until = now + datetime.timedelta(hours=1)
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED,
            completed_at=now)
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal("85.00"))
        Payment.objects.create(
            sale=sale, method="cash", amount=Decimal("85.00"),
            status="completed")

    def test_happy_path_creates_cashup_via_service(self):
        out = io.StringIO()
        call_command(
            "run_cashup", salon_id=self.salon.pk,
            since=self.since, until=self.until, note="midday",
            stdout=out)
        self.assertEqual(Cashup.objects.count(), 1)
        cashup = Cashup.objects.get()
        self.assertEqual(cashup.salon, self.salon)
        self.assertEqual(cashup.tender_totals, {"cash": "85.00"})
        self.assertEqual(cashup.total, Decimal("85.00"))
        self.assertEqual(cashup.note, "midday")
        self.assertIn("85.00", out.getvalue())
        self.assertIn("cash", out.getvalue())

    def test_happy_path_with_string_args(self):
        out = io.StringIO()
        call_command(
            "run_cashup", "--salon-id", str(self.salon.pk),
            "--since", self.since.isoformat(),
            "--until", self.until.isoformat(), stdout=out)
        self.assertEqual(Cashup.objects.count(), 1)
        self.assertEqual(Cashup.objects.get().total, Decimal("85.00"))
        self.assertEqual(Cashup.objects.get().note, "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "run_cashup", salon_id=self.salon.pk + 999,
                since=self.since, until=self.until,
                stdout=io.StringIO())
        self.assertEqual(Cashup.objects.count(), 0)

    def test_bad_datetime_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "run_cashup", salon_id=self.salon.pk,
                since="not-a-datetime", until=self.until,
                stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "run_cashup", "--salon-id", str(self.salon.pk),
                "--since", self.since.isoformat(),
                "--until", "2026-13-40T99:99:99",
                stdout=io.StringIO())
        self.assertEqual(Cashup.objects.count(), 0)
