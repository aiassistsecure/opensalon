"""Tests for the resend_receipt management command.

The command is a thin wrapper around
``checkout.receipt_resend.resend_receipt`` and
``checkout.receipt_resend.resend_receipt_for_sale``: these
tests pin that invoking it re-sends the stored receipt through
the service, that an explicit recipient is passed through, and
that missing/conflicting identifiers, unknown ids, and service
refusals fail cleanly as ``CommandError`` with nothing sent.
Fixtures are tiny synthetic records -- unit logic only.
"""
import io
from decimal import Decimal

from django.core import mail
from django.core.management import CommandError, call_command, get_commands
from django.test import TestCase, override_settings
from django.utils import timezone

from checkout.models import Payment, Receipt, Sale, SaleItem
from checkout.receipts import build_receipt, send_receipt
from clients.models import Client
from saloncore.models import Salon


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="salon@example.com",
)
class ResendReceiptCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example",
            email="client@example.com",
        )
        self.sale = Sale.objects.create(
            salon=self.salon, client=self.client,
            status=Sale.Status.COMPLETED, completed_at=timezone.now(),
        )
        SaleItem.objects.create(
            sale=self.sale, kind="service", description="Haircut",
            unit_price=Decimal("85.00"),
        )
        Payment.objects.create(
            sale=self.sale, method=Payment.Method.CASH,
            amount=Decimal("85.00"), status=Payment.Status.COMPLETED,
        )
        self.receipt = build_receipt(self.sale)

    def test_command_is_registered_to_checkout(self):
        self.assertEqual(get_commands()["resend_receipt"], "checkout")

    def test_resend_by_sale_id_matches_service(self):
        out = io.StringIO()
        call_command("resend_receipt", sale_id=self.sale.pk, stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["client@example.com"])
        self.assertIn("Haircut", mail.outbox[0].body)
        self.assertIn(f"#{self.receipt.pk}", out.getvalue())
        self.assertIn("client@example.com", out.getvalue())
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.recipient_email, "client@example.com")
        self.assertIsNotNone(self.receipt.sent_at)

    def test_resend_by_receipt_id(self):
        out = io.StringIO()
        call_command(
            "resend_receipt", receipt_id=self.receipt.pk, stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["client@example.com"])
        self.assertIn(f"#{self.receipt.pk}", out.getvalue())

    def test_resend_by_sale_id_with_string_args(self):
        out = io.StringIO()
        call_command(
            "resend_receipt", "--sale-id", str(self.sale.pk), stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["client@example.com"])

    def test_explicit_recipient_is_passed_through(self):
        call_command(
            "resend_receipt", sale_id=self.sale.pk,
            recipient="other@example.com", stdout=io.StringIO())
        self.assertEqual(mail.outbox[0].to, ["other@example.com"])
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.recipient_email, "other@example.com")

    def test_default_recipient_is_stored_recipient(self):
        send_receipt(self.receipt, recipient="original@example.com")
        mail.outbox.clear()
        call_command(
            "resend_receipt", receipt_id=self.receipt.pk,
            stdout=io.StringIO())
        self.assertEqual(mail.outbox[0].to, ["original@example.com"])

    def test_neither_identifier_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("resend_receipt", stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 0)

    def test_both_identifiers_raise_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "resend_receipt", sale_id=self.sale.pk,
                receipt_id=self.receipt.pk, stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 0)

    def test_unknown_sale_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "resend_receipt", sale_id=self.sale.pk + 999,
                stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 0)

    def test_unknown_receipt_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "resend_receipt", receipt_id=self.receipt.pk + 999,
                stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 0)

    def test_voided_sale_raises_command_error_and_sends_nothing(self):
        self.sale.status = Sale.Status.VOIDED
        self.sale.voided_at = timezone.now()
        self.sale.save(update_fields=["status", "voided_at"])
        with self.assertRaises(CommandError):
            call_command(
                "resend_receipt", sale_id=self.sale.pk,
                stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 0)

    def test_sale_without_receipt_raises_and_creates_nothing(self):
        sale = Sale.objects.create(
            salon=self.salon, client=self.client,
            status=Sale.Status.COMPLETED, completed_at=timezone.now(),
        )
        with self.assertRaises(CommandError):
            call_command(
                "resend_receipt", sale_id=sale.pk, stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(Receipt.objects.filter(sale=sale).exists())
