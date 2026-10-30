from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.cashup import compute_tender_totals, run_cashup
from checkout.models import Cashup, Payment, Sale, SaleItem
from saloncore.models import Salon


class CashupTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        now = timezone.now()
        self.since = now - timezone.timedelta(hours=1)
        self.until = now + timezone.timedelta(hours=1)

    def _sale_with_payment(self, salon, method, amount, status="completed",
                            when=None):
        sale = Sale.objects.create(
            salon=salon, status=Sale.Status.COMPLETED,
            completed_at=timezone.now(),
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
        return sale, payment

    def test_totals_by_tender_are_correct(self):
        self._sale_with_payment(self.salon, "cash", "85.00")
        self._sale_with_payment(self.salon, "cash", "15.00")
        self._sale_with_payment(self.salon, "external", "50.00")
        cashup = run_cashup(self.salon, self.since, self.until, note="midday")
        self.assertEqual(
            cashup.tender_totals, {"cash": "100.00", "external": "50.00"}
        )
        self.assertEqual(cashup.total, Decimal("150.00"))
        self.assertEqual(cashup.salon, self.salon)
        self.assertEqual(cashup.period_start, self.since)
        self.assertEqual(cashup.period_end, self.until)
        self.assertEqual(cashup.note, "midday")
        self.assertIsNotNone(cashup.created_at)

    def test_only_completed_in_period_for_this_salon_count(self):
        self._sale_with_payment(self.salon, "cash", "85.00")
        self._sale_with_payment(self.salon, "cash", "999.00", status="pending")
        self._sale_with_payment(self.salon, "cash", "999.00", status="failed")
        self._sale_with_payment(self.salon, "cash", "999.00", status="refunded")
        self._sale_with_payment(
            self.salon, "cash", "999.00",
            when=self.until + timezone.timedelta(days=1),
        )
        self._sale_with_payment(self.other, "cash", "999.00")
        cashup = run_cashup(self.salon, self.since, self.until)
        self.assertEqual(cashup.tender_totals, {"cash": "85.00"})
        self.assertEqual(cashup.total, Decimal("85.00"))

    def test_compute_tender_totals_records_nothing(self):
        self._sale_with_payment(self.salon, "cash", "85.00")
        totals = compute_tender_totals(self.salon, self.since, self.until)
        self.assertEqual(totals, {"cash": Decimal("85.00")})
        self.assertEqual(Cashup.objects.count(), 0)

    def test_empty_period_is_zero_cashup(self):
        cashup = run_cashup(self.salon, self.since, self.until)
        self.assertEqual(cashup.tender_totals, {})
        self.assertEqual(cashup.total, Decimal("0.00"))

    def test_two_cashups_same_day_both_succeed(self):
        self._sale_with_payment(self.salon, "cash", "85.00")
        first = run_cashup(self.salon, self.since, self.until)
        second = run_cashup(self.salon, self.since, self.until)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(Cashup.objects.count(), 2)
        self.assertEqual(first.total, Decimal("85.00"))
        self.assertEqual(second.total, Decimal("85.00"))

    def test_sale_after_cashup_is_unaffected_and_counted_next_time(self):
        self._sale_with_payment(self.salon, "cash", "85.00")
        first = run_cashup(self.salon, self.since, self.until)
        sale, _payment = self._sale_with_payment(self.salon, "external", "40.00")
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.COMPLETED)
        self.assertEqual(sale.total, Decimal("40.00"))
        self.assertEqual(Payment.objects.filter(sale=sale).count(), 1)
        second = run_cashup(self.salon, self.since, self.until)
        self.assertEqual(second.total, Decimal("125.00"))
        first.refresh_from_db()
        self.assertEqual(first.total, Decimal("85.00"))  # snapshot unchanged

    def test_inverted_period_raises(self):
        with self.assertRaises(ValueError):
            run_cashup(self.salon, self.until, self.since)

    def test_cashup_is_snapshot_not_rewritten_by_later_payments(self):
        self._sale_with_payment(self.salon, "cash", "85.00")
        cashup = run_cashup(self.salon, self.since, self.until)
        self._sale_with_payment(self.salon, "cash", "10.00")
        cashup.refresh_from_db()
        self.assertEqual(cashup.tender_totals, {"cash": "85.00"})
        self.assertEqual(cashup.total, Decimal("85.00"))
