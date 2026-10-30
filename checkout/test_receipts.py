from decimal import Decimal

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from catalog.models import Product
from checkout.models import Payment, Sale, SaleItem
from checkout.receipts import build_receipt, render_receipt_text, send_receipt
from clients.models import Client
from saloncore.models import Salon


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="salon@example.com",
)
class ReceiptTests(TestCase):
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
        SaleItem.objects.create(
            sale=self.sale, kind="product", description="Shampoo",
            quantity=2, unit_price=Decimal("24.00"),
        )
        Payment.objects.create(
            sale=self.sale, method=Payment.Method.CASH,
            amount=Decimal("133.00"), status=Payment.Status.COMPLETED,
        )

    def test_build_receipt_snapshots_lines_total_and_tender(self):
        receipt = build_receipt(self.sale)
        self.assertEqual(receipt.sale, self.sale)
        self.assertEqual(self.sale.receipt, receipt)
        self.assertEqual(receipt.salon_name, "Example Salon")
        self.assertEqual(receipt.total, Decimal("133.00"))
        self.assertEqual(len(receipt.lines), 2)
        self.assertEqual(receipt.lines[0]["description"], "Haircut")
        self.assertEqual(receipt.lines[0]["line_total"], "85.00")
        self.assertEqual(receipt.lines[1]["quantity"], 2)
        self.assertEqual(
            receipt.tender,
            [{"method": "cash", "amount": "133.00", "status": "completed"}],
        )
        self.assertIsNotNone(receipt.issued_at)
        self.assertIsNone(receipt.sent_at)

    def test_receipt_is_snapshot_not_live(self):
        receipt = build_receipt(self.sale)
        SaleItem.objects.create(
            sale=self.sale, kind="service", description="Extra",
            unit_price=Decimal("10.00"),
        )
        receipt.refresh_from_db()
        self.assertEqual(receipt.total, Decimal("133.00"))
        self.assertEqual(len(receipt.lines), 2)

    def test_build_receipt_is_idempotent(self):
        first = build_receipt(self.sale)
        self.assertEqual(build_receipt(self.sale).pk, first.pk)

    def test_render_text_contains_lines_total_tender(self):
        text = render_receipt_text(build_receipt(self.sale))
        self.assertIn("Example Salon", text)
        self.assertIn("Haircut", text)
        self.assertIn("Total: 133.00", text)
        self.assertIn("cash", text)

    def test_send_receipt_emails_client_via_locmem(self):
        receipt = send_receipt(build_receipt(self.sale))
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["client@example.com"])
        self.assertEqual(msg.from_email, "salon@example.com")
        self.assertIn("Total: 133.00", msg.body)
        receipt.refresh_from_db()
        self.assertEqual(receipt.recipient_email, "client@example.com")
        self.assertIsNotNone(receipt.sent_at)

    def test_send_receipt_explicit_recipient_overrides(self):
        send_receipt(build_receipt(self.sale), recipient="other@example.com")
        self.assertEqual(mail.outbox[0].to, ["other@example.com"])

    def test_send_receipt_without_recipient_raises(self):
        sale = Sale.objects.create(salon=self.salon)
        with self.assertRaises(ValueError):
            send_receipt(build_receipt(sale))
        self.assertEqual(len(mail.outbox), 0)
