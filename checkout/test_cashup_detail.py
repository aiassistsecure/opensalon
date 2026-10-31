import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.cashup_detail import cashup_detail
from checkout.models import Payment, Refund, Sale, SaleItem
from checkout.refunds import record_refund
from checkout.void import void_sale
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)


class CashupDetailTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")

    def _completed_sale(self, salon, method, amount, when=None):
        sale = Sale.objects.create(
            salon=salon, status=Sale.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal(amount),
        )
        payment = Payment.objects.create(
            sale=sale, method=method, amount=Decimal(amount),
            status=Payment.Status.COMPLETED,
        )
        if when is not None:
            stamp = timezone.make_aware(
                datetime.datetime.combine(when, datetime.time(12, 0))
            )
            Payment.objects.filter(pk=payment.pk).update(created_at=stamp)
            Sale.objects.filter(pk=sale.pk).update(created_at=stamp)
        return sale

    def test_empty_range_is_all_zeroes(self):
        detail = cashup_detail(self.salon, DAY, DAY)
        self.assertEqual(detail.gross, Decimal("0.00"))
        self.assertEqual(detail.refunds, Decimal("0.00"))
        self.assertEqual(detail.voids, Decimal("0.00"))
        self.assertEqual(detail.net, Decimal("0.00"))
        for tender in Payment.Method.values:
            row = detail.by_tender[tender]
            self.assertEqual(row.gross, Decimal("0.00"))
            self.assertEqual(row.net, Decimal("0.00"))
            self.assertEqual(row.payment_count, 0)

    def _refund_on(self, sale, amount, tender, when):
        refund = record_refund(sale, Decimal(amount), tender=tender)
        stamp = timezone.make_aware(
            datetime.datetime.combine(when, datetime.time(13, 0))
        )
        Refund.objects.filter(pk=refund.pk).update(created_at=stamp)
        return refund

    def test_sales_and_refund_net_per_tender(self):
        sale = self._completed_sale(self.salon, "cash", "100.00", when=DAY)
        self._refund_on(sale, "20.00", "cash", DAY)
        detail = cashup_detail(self.salon, DAY, DAY)
        cash = detail.by_tender["cash"]
        self.assertEqual(cash.gross, Decimal("100.00"))
        self.assertEqual(cash.refunds, Decimal("20.00"))
        self.assertEqual(cash.net, Decimal("80.00"))
        self.assertEqual(detail.gross, Decimal("100.00"))
        self.assertEqual(detail.refunds, Decimal("20.00"))
        self.assertEqual(detail.net, Decimal("80.00"))

    def test_voided_sale_excluded_from_gross_reported_as_void(self):
        self._completed_sale(self.salon, "cash", "85.00", when=DAY)
        voided = self._completed_sale(self.salon, "cash", "60.00", when=DAY)
        void_sale(voided, "entered in error")
        detail = cashup_detail(self.salon, DAY, DAY)
        cash = detail.by_tender["cash"]
        self.assertEqual(cash.gross, Decimal("85.00"))
        self.assertEqual(cash.voids, Decimal("60.00"))
        self.assertEqual(cash.void_count, 1)
        # Voids are already out of gross, so net is not cut twice.
        self.assertEqual(cash.net, Decimal("85.00"))
        self.assertEqual(detail.voids, Decimal("60.00"))
        self.assertEqual(detail.net, Decimal("85.00"))

    def test_per_tender_split_and_other_salon_excluded(self):
        self._completed_sale(self.salon, "cash", "100.00", when=DAY)
        external = self._completed_sale(
            self.salon, "external", "50.00", when=DAY
        )
        self._refund_on(external, "10.00", "external", DAY)
        self._completed_sale(self.other, "cash", "999.00", when=DAY)
        self._completed_sale(
            self.salon, "cash", "999.00",
            when=DAY + datetime.timedelta(days=7),
        )
        detail = cashup_detail(self.salon, DAY, DAY + datetime.timedelta(days=1))
        self.assertEqual(detail.by_tender["cash"].gross, Decimal("100.00"))
        self.assertEqual(detail.by_tender["cash"].net, Decimal("100.00"))
        ext = detail.by_tender["external"]
        self.assertEqual(ext.gross, Decimal("50.00"))
        self.assertEqual(ext.refunds, Decimal("10.00"))
        self.assertEqual(ext.net, Decimal("40.00"))
        self.assertEqual(detail.gross, Decimal("150.00"))
        self.assertEqual(detail.net, Decimal("140.00"))
        self.assertEqual(Refund.objects.count(), 1)

    def test_inverted_range_raises(self):
        with self.assertRaises(ValueError):
            cashup_detail(
                self.salon, DAY + datetime.timedelta(days=1), DAY
            )
