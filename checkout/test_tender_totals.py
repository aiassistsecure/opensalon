import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Cashup, Payment, Sale, SaleItem
from checkout.tender_totals import tender_totals, totals_by_tender
from saloncore.models import Salon


class TenderTotalsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        now = timezone.now()
        self.since = now - timezone.timedelta(hours=1)
        self.until = now + timezone.timedelta(hours=1)

    def _pay(self, salon, method, amount, status="completed",
             sale_status="completed", when=None):
        sale = Sale.objects.create(
            salon=salon, status=sale_status, completed_at=timezone.now(),
        )
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal(amount),
        )
        payment = Payment.objects.create(
            sale=sale, method=method, amount=Decimal(amount), status=status,
        )
        if when is not None:
            Payment.objects.filter(pk=payment.pk).update(created_at=when)
        return payment

    def test_mixed_tenders_sum_correctly(self):
        self._pay(self.salon, "cash", "85.00")
        self._pay(self.salon, "cash", "15.00")
        self._pay(self.salon, "external", "50.00")
        result = tender_totals(self.since, self.until)
        self.assertEqual(
            result.by_method,
            {"cash": Decimal("100.00"), "external": Decimal("50.00")},
        )
        self.assertEqual(result.total, Decimal("150.00"))
        self.assertEqual(result.count, 3)
        self.assertEqual(result["cash"], Decimal("100.00"))
        self.assertEqual(
            totals_by_tender(self.since, self.until), result.by_method
        )

    def test_refunds_and_non_completed_excluded(self):
        self._pay(self.salon, "cash", "85.00")
        self._pay(self.salon, "cash", "999.00", status="refunded")
        self._pay(self.salon, "cash", "999.00", status="pending")
        self._pay(self.salon, "cash", "999.00", status="failed")
        result = tender_totals(self.since, self.until)
        self.assertEqual(result.by_method["cash"], Decimal("85.00"))
        self.assertEqual(result.total, Decimal("85.00"))
        self.assertEqual(result.count, 1)

    def test_voided_sale_payments_excluded(self):
        self._pay(self.salon, "cash", "85.00")
        self._pay(self.salon, "cash", "999.00", sale_status="voided")
        result = tender_totals(self.since, self.until)
        self.assertEqual(result.total, Decimal("85.00"))

    def test_empty_range_returns_zeros(self):
        result = tender_totals(self.since, self.until)
        self.assertEqual(
            result.by_method,
            {"cash": Decimal("0.00"), "external": Decimal("0.00")},
        )
        self.assertEqual(result.total, Decimal("0.00"))
        self.assertEqual(result.count, 0)

    def test_out_of_range_and_salon_filter(self):
        self._pay(self.salon, "cash", "85.00")
        self._pay(self.other, "cash", "40.00")
        self._pay(self.salon, "cash", "999.00",
                  when=self.until + timezone.timedelta(days=1))
        scoped = tender_totals(self.since, self.until, salon=self.salon)
        self.assertEqual(scoped.total, Decimal("85.00"))
        unscoped = tender_totals(self.since, self.until)
        self.assertEqual(unscoped.total, Decimal("125.00"))

    def test_date_range_covers_whole_days(self):
        today = timezone.localdate()
        self._pay(self.salon, "cash", "60.00")
        result = tender_totals(today, today)
        self.assertEqual(result.total, Decimal("60.00"))
        yesterday = today - datetime.timedelta(days=1)
        self.assertEqual(tender_totals(yesterday, yesterday).total,
                         Decimal("0.00"))

    def test_read_only_records_nothing(self):
        self._pay(self.salon, "cash", "85.00")
        tender_totals(self.since, self.until)
        self.assertEqual(Cashup.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 1)

    def test_inverted_range_raises(self):
        with self.assertRaises(ValueError):
            tender_totals(self.until, self.since)
