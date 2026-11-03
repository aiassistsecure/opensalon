"""Tests for the record_refund management command.

The command is a thin wrapper around
``checkout.refunds.record_refund``: these tests pin that a real
run records through that service, that ``--dry-run`` previews
(amount, tender, resulting refund total) while writing nothing,
and that service refusals surface as ``CommandError``.
Fixtures are tiny synthetic records -- unit logic only.
"""
import io
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.models import Payment, Refund, Sale, SaleItem
from checkout.refunds import refund_total
from saloncore.models import Salon


class RecordRefundCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Example Salon", timezone="UTC")
        self.sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED,
            completed_at=timezone.now())
        SaleItem.objects.create(
            sale=self.sale, kind="service", description="Haircut",
            unit_price=Decimal("85.00"))
        Payment.objects.create(
            sale=self.sale, method=Payment.Method.CASH,
            amount=Decimal("85.00"), status=Payment.Status.COMPLETED)

    def test_happy_path_records_refund_via_service(self):
        out = io.StringIO()
        call_command(
            "record_refund", sale_id=self.sale.pk, amount="20.00",
            reason="service issue", tender="cash", stdout=out)
        refund = Refund.objects.get()
        self.assertEqual(refund.amount, Decimal("20.00"))
        self.assertEqual(refund.tender, "cash")
        self.assertEqual(refund.reason, "service issue")
        self.assertIn("20.00", out.getvalue())
        self.assertIn("cash", out.getvalue())
        self.assertIn("refund total 20.00", out.getvalue())

    def test_dry_run_previews_and_writes_nothing(self):
        call_command(
            "record_refund", sale_id=self.sale.pk, amount="30.00",
            tender="cash", stdout=io.StringIO())
        out = io.StringIO()
        call_command(
            "record_refund", sale_id=self.sale.pk, amount="10.00",
            dry_run=True, stdout=out)
        self.assertEqual(Refund.objects.count(), 1)
        self.assertEqual(refund_total(self.sale), Decimal("30.00"))
        text = out.getvalue()
        self.assertIn("Dry run", text)
        self.assertIn("10.00", text)
        self.assertIn("cash", text)
        self.assertIn("refund total would be 40.00", text)

    def test_dry_run_refusal_on_open_sale_writes_nothing(self):
        open_sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.OPEN)
        with self.assertRaises(CommandError):
            call_command(
                "record_refund", sale_id=open_sale.pk,
                amount="10.00", dry_run=True, stdout=io.StringIO())
        self.assertEqual(Refund.objects.count(), 0)

    def test_refund_on_non_completed_sale_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "record_refund", sale_id=self.sale.pk,
                amount="85.01", tender="cash", stdout=io.StringIO())
        self.assertEqual(Refund.objects.count(), 0)

    def test_unknown_sale_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "record_refund", sale_id=self.sale.pk + 999,
                amount="10.00", stdout=io.StringIO())
        self.assertEqual(Refund.objects.count(), 0)
