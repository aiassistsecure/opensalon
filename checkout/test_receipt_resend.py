from decimal import Decimal

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from checkout.models import Payment, Receipt, Sale, SaleItem
from checkout.receipt_resend import resend_receipt, resend_receipt_for_sale
from checkout.receipts import build_receipt, send_receipt
from clients.models import Client
from saloncore.models import Salon


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="salon@example.com",
)
class ReceiptResendTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example",
            email="client@example.com",
        )
        self.sale = Sale.objects.create(
            salon=self.salon, client=self.client, status=Sale.Status.COMPLETED,
            completed_at=timezone.now(),
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

    def test_resend_emails_existing_receipt_again(self):
        send_receipt(self.receipt)
        self.assertEqual(len(mail.outbox), 1)
        result = resend_receipt(self.receipt)
        self.assertIs(result, self.receipt)
        self.assertEqual(len(mail.outbox), 2)
        msg = mail.outbox[1]
        self.assertEqual(msg.to, ["client@example.com"])
        self.assertEqual(msg.from_email, "salon@example.com")
        self.assertIn("Haircut", msg.body)
        self.assertIn("Total: 85.00", msg.body)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.recipient_email, "client@example.com")
        self.assertIsNotNone(self.receipt.sent_at)

    def test_resend_defaults_to_stored_recipient(self):
        send_receipt(self.receipt, recipient="original@example.com")
        self.client.email = "changed@example.com"
        self.client.save(update_fields=["email"])
        resend_receipt(self.receipt)
        self.assertEqual(mail.outbox[-1].to, ["original@example.com"])

    def test_resend_explicit_recipient_overrides_and_is_recorded(self):
        resend_receipt(self.receipt, recipient="other@example.com")
        self.assertEqual(mail.outbox[0].to, ["other@example.com"])
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.recipient_email, "other@example.com")
        self.assertIsNotNone(self.receipt.sent_at)

    def test_resend_uses_stored_snapshot_not_live_sale(self):
        SaleItem.objects.create(
            sale=self.sale, kind="service", description="Extra",
            unit_price=Decimal("10.00"),
        )
        resend_receipt(self.receipt)
        self.assertIn("Total: 85.00", mail.outbox[0].body)
        self.assertNotIn("Extra", mail.outbox[0].body)
        self.assertEqual(Receipt.objects.count(), 1)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.total, Decimal("85.00"))
        self.assertEqual(len(self.receipt.lines), 1)

    def test_resend_voided_sale_raises_and_sends_nothing(self):
        self.sale.status = Sale.Status.VOIDED
        self.sale.voided_at = timezone.now()
        self.sale.save(update_fields=["status", "voided_at"])
        with self.assertRaises(ValueError):
            resend_receipt(self.receipt)
        self.assertEqual(len(mail.outbox), 0)
        self.receipt.refresh_from_db()
        self.assertIsNone(self.receipt.sent_at)

    def test_resend_open_sale_raises_and_sends_nothing(self):
        self.sale.status = Sale.Status.OPEN
        self.sale.save(update_fields=["status"])
        with self.assertRaises(ValueError):
            resend_receipt(self.receipt)
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_none_receipt_raises(self):
        with self.assertRaises(ValueError):
            resend_receipt(None)
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_without_any_recipient_raises(self):
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        receipt = build_receipt(sale)
        with self.assertRaises(ValueError):
            resend_receipt(receipt)
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_for_sale_uses_existing_receipt(self):
        result = resend_receipt_for_sale(self.sale)
        self.assertEqual(result.pk, self.receipt.pk)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["client@example.com"])

    def test_resend_for_sale_without_receipt_raises_and_creates_nothing(self):
        sale = Sale.objects.create(
            salon=self.salon, client=self.client,
            status=Sale.Status.COMPLETED, completed_at=timezone.now(),
        )
        with self.assertRaises(ValueError):
            resend_receipt_for_sale(sale)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(Receipt.objects.filter(sale=sale).exists())

    def test_resend_for_sale_none_raises(self):
        with self.assertRaises(ValueError):
            resend_receipt_for_sale(None)
