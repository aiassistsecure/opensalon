import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Cashup, Payment, Sale, SaleItem
from checkout.tender_mix import tender_mix
from saloncore.models import Salon


class TenderMixTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        now = timezone.now()
        self.since = now - timezone.timedelta(hours=1)
        self.until = now + timezone.timedelta(hours=1)

    def _pay(self, salon, method, amount, status="completed",
             sale_status="completed", when=None):
        sale = Sale.objects.create(
            salon=salon, status=sale_status, completed_at=timezone.now())
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal(amount))
        payment = Payment.objects.create(
            sale=sale, method=method, amount=Decimal(amount), status=status)
        if when is not None:
            Payment.objects.filter(pk=payment.pk).update(created_at=when)
        return payment

    def test_mixed_tenders_totals_and_shares(self):
        self._pay(self.salon, "cash", "85.00")
        self._pay(self.salon, "cash", "15.00")
        self._pay(self.salon, "external", "50.00")
        result = tender_mix(self.salon, self.since, self.until)
        self.assertEqual(result.total, Decimal("150.00"))
        self.assertEqual(result.count, 3)
        self.assertEqual(result.salon_id, self.salon.pk)
        self.assertEqual(
            result.by_method,
            {"cash": Decimal("100.00"), "external": Decimal("50.00")})
        self.assertEqual(
            result.shares,
            {"cash": Decimal("66.67"), "external": Decimal("33.33")})
        self.assertEqual(
            sum(result.shares.values()), Decimal("100.00"))
        entry = result["cash"]
        self.assertEqual(entry.total, Decimal("100.00"))
        self.assertEqual(entry.amount, Decimal("100.00"))
        self.assertEqual(entry.share_percent, Decimal("66.67"))
        self.assertEqual(
            [e.method for e in result.entries], ["cash", "external"])

    def test_non_completed_and_voided_excluded(self):
        self._pay(self.salon, "cash", "80.00")
        self._pay(self.salon, "external", "20.00")
        self._pay(self.salon, "cash", "999.00", status="refunded")
        self._pay(self.salon, "cash", "999.00", status="pending")
        self._pay(self.salon, "cash", "999.00", status="failed")
        self._pay(self.salon, "cash", "999.00", sale_status="voided")
        result = tender_mix(self.salon, self.since, self.until)
        self.assertEqual(result.total, Decimal("100.00"))
        self.assertEqual(result.count, 2)
        self.assertEqual(result.shares["cash"], Decimal("80.00"))
        self.assertEqual(result.shares["external"], Decimal("20.00"))

    def test_empty_window_zero_totals_and_none_shares(self):
        result = tender_mix(self.salon, self.since, self.until)
        self.assertEqual(result.total, Decimal("0.00"))
        self.assertEqual(result.count, 0)
        self.assertEqual(
            result.by_method,
            {"cash": Decimal("0.00"), "external": Decimal("0.00")})
        self.assertEqual(
            result.shares, {"cash": None, "external": None})
        for entry in result.entries:
            self.assertIsNone(entry.share_percent)

    def test_salon_scoping_and_out_of_range(self):
        self._pay(self.salon, "cash", "75.00")
        self._pay(self.other, "cash", "999.00")
        self._pay(self.salon, "cash", "999.00",
                  when=self.until + timezone.timedelta(days=1))
        result = tender_mix(self.salon, self.since, self.until)
        self.assertEqual(result.total, Decimal("75.00"))
        self.assertEqual(result.shares["cash"], Decimal("100.00"))
        self.assertEqual(result.shares["external"], Decimal("0.00"))

    def test_date_window_covers_whole_days(self):
        today = timezone.localdate()
        self._pay(self.salon, "cash", "60.00")
        result = tender_mix(self.salon, today, today)
        self.assertEqual(result.total, Decimal("60.00"))
        yesterday = today - datetime.timedelta(days=1)
        empty = tender_mix(self.salon, yesterday, yesterday)
        self.assertEqual(empty.total, Decimal("0.00"))
        self.assertIsNone(empty.shares["cash"])

    def test_reversed_window_raises(self):
        with self.assertRaises(ValueError):
            tender_mix(self.salon, self.until, self.since)
        today = timezone.localdate()
        with self.assertRaises(ValueError):
            tender_mix(
                self.salon, today, today - datetime.timedelta(days=1))

    def test_missing_salon_raises(self):
        with self.assertRaises(ValueError):
            tender_mix(None, self.since, self.until)

    def test_read_only_records_nothing(self):
        self._pay(self.salon, "cash", "85.00")
        tender_mix(self.salon, self.since, self.until)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(Cashup.objects.count(), 0)
