"""Tests for the void_sale management command.

The command is a thin wrapper around
``checkout.void.void_sale``: these tests pin that a real run
voids through that service, that ``--dry-run`` previews the
void (resulting status) while writing nothing, and that
service refusals surface as ``CommandError``. Fixtures are
tiny synthetic records -- unit logic only.
"""
import io
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.models import Payment, Sale, SaleItem
from saloncore.models import Salon


class VoidSaleCommandTests(TestCase):
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

    def test_happy_path_voids_via_service(self):
        out = io.StringIO()
        call_command(
            "void_sale", sale_id=self.sale.pk,
            reason="rung up twice", stdout=out)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, Sale.Status.VOIDED)
        self.assertEqual(self.sale.void_reason, "rung up twice")
        self.assertIsNotNone(self.sale.voided_at)
        self.assertIn("voided", out.getvalue())

    def test_dry_run_previews_and_writes_nothing(self):
        out = io.StringIO()
        call_command(
            "void_sale", sale_id=self.sale.pk,
            reason="entered in error", dry_run=True, stdout=out)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, Sale.Status.COMPLETED)
        self.assertEqual(self.sale.void_reason, "")
        self.assertIsNone(self.sale.voided_at)
        text = out.getvalue()
        self.assertIn("Dry run", text)
        self.assertIn("entered in error", text)
        self.assertIn("sale status would be voided", text)
        # Real run still works after a dry run.
        call_command(
            "void_sale", sale_id=self.sale.pk,
            reason="entered in error", stdout=io.StringIO())
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, Sale.Status.VOIDED)

    def test_refusals_are_command_errors_and_change_nothing(self):
        open_sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.OPEN)
        for sale_id, dry_run in (
                (open_sale.pk, False), (open_sale.pk, True),
                (self.sale.pk + 999, False)):
            with self.assertRaises(CommandError):
                call_command(
                    "void_sale", sale_id=sale_id, reason="x",
                    dry_run=dry_run, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "void_sale", sale_id=self.sale.pk, reason="   ",
                stdout=io.StringIO())
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, Sale.Status.COMPLETED)
        self.assertIsNone(self.sale.voided_at)
