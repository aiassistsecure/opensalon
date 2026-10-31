from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Payment, Refund, Sale, SaleItem
from checkout.refunds import record_refund, refund_total, refunds_for_sale
from saloncore.models import Salon


class RefundTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")

    def _completed_sale(self, price="85.00", method=Payment.Method.CASH):
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal(price),
        )
        Payment.objects.create(
            sale=sale, method=method, amount=Decimal(price),
            status=Payment.Status.COMPLETED,
        )
        return sale

    def test_happy_path_records_refund_without_mutating_sale_or_payment(self):
        sale = self._completed_sale()
        refund = record_refund(sale, Decimal("20.00"), reason="service issue", tender="cash")
        self.assertEqual(refund.sale, sale)
        self.assertEqual(refund.amount, Decimal("20.00"))
        self.assertEqual(refund.reason, "service issue")
        self.assertEqual(refund.tender, "cash")
        self.assertIsNotNone(refund.created_at)
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.COMPLETED)
        self.assertEqual(sale.total, Decimal("85.00"))
        payment = Payment.objects.get(sale=sale)
        self.assertEqual(payment.status, Payment.Status.COMPLETED)
        self.assertEqual(payment.amount, Decimal("85.00"))

    def test_tender_defaults_to_original_payment_tender(self):
        sale = self._completed_sale(method=Payment.Method.EXTERNAL)
        refund = record_refund(sale, Decimal("10.00"))
        self.assertEqual(refund.tender, "external")

    def test_partial_refunds_sum(self):
        sale = self._completed_sale()
        record_refund(sale, Decimal("30.00"), tender="cash")
        record_refund(sale, Decimal("25.00"), tender="cash")
        self.assertEqual(refund_total(sale), Decimal("55.00"))
        self.assertEqual(
            [r.amount for r in refunds_for_sale(sale)],
            [Decimal("30.00"), Decimal("25.00")],
        )
        # The remainder can still be refunded, exactly.
        record_refund(sale, Decimal("30.00"), tender="cash")
        self.assertEqual(refund_total(sale), Decimal("85.00"))

    def test_refund_total_and_list_empty_for_unrefunded_sale(self):
        sale = self._completed_sale()
        self.assertEqual(refund_total(sale), Decimal("0.00"))
        self.assertEqual(list(refunds_for_sale(sale)), [])

    def test_over_refund_refused(self):
        sale = self._completed_sale()
        with self.assertRaises(ValueError):
            record_refund(sale, Decimal("85.01"), tender="cash")
        record_refund(sale, Decimal("80.00"), tender="cash")
        with self.assertRaises(ValueError):
            record_refund(sale, Decimal("5.01"), tender="cash")
        self.assertEqual(Refund.objects.filter(sale=sale).count(), 1)
        self.assertEqual(refund_total(sale), Decimal("80.00"))

    def test_voided_sale_refused(self):
        sale = self._completed_sale()
        sale.status = Sale.Status.VOIDED
        sale.voided_at = timezone.now()
        sale.save(update_fields=["status", "voided_at"])
        with self.assertRaises(ValueError):
            record_refund(sale, Decimal("10.00"), tender="cash")
        self.assertEqual(Refund.objects.count(), 0)

    def test_open_sale_refused(self):
        sale = Sale.objects.create(salon=self.salon, status=Sale.Status.OPEN)
        with self.assertRaises(ValueError):
            record_refund(sale, Decimal("10.00"), tender="cash")

    def test_non_positive_amount_refused(self):
        sale = self._completed_sale()
        for bad in (Decimal("0.00"), Decimal("-5.00")):
            with self.assertRaises(ValueError):
                record_refund(sale, bad, tender="cash")
        self.assertEqual(Refund.objects.count(), 0)

    def test_tender_must_match_original_payment(self):
        sale = self._completed_sale(method=Payment.Method.CASH)
        with self.assertRaises(ValueError):
            record_refund(sale, Decimal("10.00"), tender="external")
        with self.assertRaises(ValueError):
            record_refund(sale, Decimal("10.00"), tender="bogus")
        self.assertEqual(Refund.objects.count(), 0)
