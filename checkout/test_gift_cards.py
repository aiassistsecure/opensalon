from decimal import Decimal

from django.test import TestCase

from checkout.models import GiftCard, GiftCardTransaction, Sale
from clients.models import Client
from saloncore.models import Salon


class GiftCardTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.purchaser = Client.objects.create(
            salon=self.salon, first_name="Pat", last_name="Buyer"
        )

    def _card(self, amount="100.00", code="GC-0001", **kwargs):
        return GiftCard.objects.create(
            salon=self.salon,
            code=code,
            initial_amount=Decimal(amount),
            purchaser=self.purchaser,
            **kwargs,
        )

    def test_issue_creates_balance(self):
        card = self._card(recipient_name="Sam")
        self.assertEqual(card.status, GiftCard.Status.ACTIVE)
        self.assertEqual(card.balance(), Decimal("100.00"))
        self.assertEqual(card.purchaser, self.purchaser)
        self.assertEqual(card.recipient_name, "Sam")
        self.assertIsNotNone(card.issued_at)

    def test_redeem_reduces_balance(self):
        card = self._card()
        txn = card.redeem(Decimal("30.00"))
        self.assertEqual(txn.kind, GiftCardTransaction.Kind.REDEEM)
        self.assertEqual(txn.amount, Decimal("30.00"))
        self.assertEqual(card.balance(), Decimal("70.00"))
        self.assertEqual(card.status, GiftCard.Status.ACTIVE)

    def test_redeem_records_sale_link(self):
        card = self._card()
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED
        )
        txn = card.redeem(Decimal("10.00"), sale=sale, note="till 1")
        self.assertEqual(txn.sale, sale)
        self.assertEqual(txn.note, "till 1")

    def test_redeem_over_balance_raises(self):
        card = self._card()
        with self.assertRaises(ValueError):
            card.redeem(Decimal("100.01"))
        self.assertEqual(card.balance(), Decimal("100.00"))
        self.assertEqual(card.transactions.count(), 0)

    def test_redeem_on_void_card_raises(self):
        card = self._card()
        card.status = GiftCard.Status.VOID
        card.save()
        with self.assertRaises(ValueError):
            card.redeem(Decimal("10.00"))
        self.assertEqual(card.transactions.count(), 0)

    def test_balance_after_multiple_redeems(self):
        card = self._card()
        card.redeem(Decimal("25.00"))
        card.redeem(Decimal("25.00"))
        card.redeem(Decimal("10.00"))
        self.assertEqual(card.balance(), Decimal("40.00"))
        self.assertEqual(
            card.transactions.filter(
                kind=GiftCardTransaction.Kind.REDEEM
            ).count(),
            3,
        )

    def test_redeem_full_balance_marks_card_redeemed(self):
        card = self._card(amount="50.00")
        card.redeem(Decimal("50.00"))
        card.refresh_from_db()
        self.assertEqual(card.balance(), Decimal("0.00"))
        self.assertEqual(card.status, GiftCard.Status.REDEEMED)
        with self.assertRaises(ValueError):
            card.redeem(Decimal("1.00"))
