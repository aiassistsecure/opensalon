import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Payment, Refund, Sale, SaleItem
from checkout.refund_report import refund_totals, refunds_by_day
from checkout.refunds import record_refund
from saloncore.models import Salon


class RefundReportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.day = datetime.date(2026, 10, 3)

    def _at(self, day, hour=12):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, 0)),
            datetime.timezone.utc,
        )

    def _completed_sale(self, salon=None, price="100.00",
                        method=Payment.Method.CASH):
        salon = salon or self.salon
        sale = Sale.objects.create(
            salon=salon, status=Sale.Status.COMPLETED,
            completed_at=self._at(self.day),
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

    def _refund(self, sale, amount, day=None, tender=None, hour=12):
        refund = record_refund(
            sale, Decimal(amount), tender=tender or sale.payments.get().method
        )
        Refund.objects.filter(pk=refund.pk).update(
            created_at=self._at(day or self.day, hour=hour)
        )
        refund.refresh_from_db()
        return refund

    def test_refunds_on_the_day_counted(self):
        sale = self._completed_sale()
        self._refund(sale, "20.00")
        self._refund(sale, "15.00")
        result = refunds_by_day(self.salon, self.day)
        self.assertEqual(result.refund_count, 2)
        self.assertEqual(result.count, 2)
        self.assertEqual(result.total, Decimal("35.00"))
        self.assertEqual(result.day, self.day)

    def test_other_days_excluded(self):
        sale = self._completed_sale(price="300.00")
        self._refund(sale, "20.00")
        self._refund(sale, "99.00", day=self.day - datetime.timedelta(days=1))
        self._refund(sale, "88.00", day=self.day + datetime.timedelta(days=1))
        result = refunds_by_day(self.salon, self.day)
        self.assertEqual(result.refund_count, 1)
        self.assertEqual(result.total, Decimal("20.00"))
        # The other salon's refunds never leak in either.
        other_sale = self._completed_sale(salon=self.other)
        self._refund(other_sale, "77.00")
        self.assertEqual(refunds_by_day(self.salon, self.day).total,
                         Decimal("20.00"))

    def test_tender_grouping(self):
        cash_sale = self._completed_sale(method=Payment.Method.CASH)
        ext_sale = self._completed_sale(method=Payment.Method.EXTERNAL)
        self._refund(cash_sale, "20.00")
        self._refund(cash_sale, "5.00")
        self._refund(ext_sale, "30.00")
        result = refunds_by_day(self.salon, self.day)
        self.assertEqual(result.refund_count, 3)
        self.assertEqual(result.total, Decimal("55.00"))
        self.assertEqual(result.by_tender["cash"], Decimal("25.00"))
        self.assertEqual(result.by_tender["external"], Decimal("30.00"))
        self.assertEqual(result["cash"], Decimal("25.00"))
        self.assertEqual(result.counts_by_tender["cash"], 2)
        self.assertEqual(result.counts_by_tender["external"], 1)

    def test_empty_day_returns_zeroes(self):
        result = refunds_by_day(self.salon, self.day)
        self.assertEqual(result.refund_count, 0)
        self.assertEqual(result.total, Decimal("0.00"))
        self.assertEqual(
            result.by_tender,
            {"cash": Decimal("0.00"), "external": Decimal("0.00")},
        )
        self.assertEqual(result.counts_by_tender, {"cash": 0, "external": 0})

    def test_voided_sale_refund_not_counted(self):
        sale = self._completed_sale()
        self._refund(sale, "20.00")
        # Force the impossible state directly: a refund row on a
        # sale that is then voided must not be counted (record_refund
        # itself refuses voided sales, so this row can only exist
        # by bypassing the service).
        Sale.objects.filter(pk=sale.pk).update(
            status=Sale.Status.VOIDED, voided_at=self._at(self.day)
        )
        result = refunds_by_day(self.salon, self.day)
        self.assertEqual(result.refund_count, 0)
        self.assertEqual(result.total, Decimal("0.00"))
        sale.refresh_from_db()
        with self.assertRaises(ValueError):
            record_refund(sale, Decimal("10.00"), tender="cash")

    def test_refund_totals_per_day_range(self):
        sale = self._completed_sale(price="300.00")
        day2 = self.day + datetime.timedelta(days=1)
        day3 = self.day + datetime.timedelta(days=2)
        self._refund(sale, "20.00")
        self._refund(sale, "30.00", day=day2)
        self._refund(sale, "99.00", day=day3 + datetime.timedelta(days=1))
        result = refund_totals(self.salon, self.day, day3)
        self.assertEqual(result.refund_count, 2)
        self.assertEqual(result.total, Decimal("50.00"))
        self.assertEqual(result.by_tender["cash"], Decimal("50.00"))
        self.assertEqual(result.by_day[self.day].total, Decimal("20.00"))
        self.assertEqual(result.by_day[day2].refund_count, 1)
        self.assertEqual(result.by_day[day3].total, Decimal("0.00"))
        self.assertEqual([d.day for d in result.days],
                         [self.day, day2, day3])
        empty = refund_totals(self.salon, day3, day3)
        self.assertEqual(empty.refund_count, 0)
        self.assertEqual(empty.total, Decimal("0.00"))

    def test_salon_timezone_judges_the_day(self):
        # 01:00 UTC on Oct 3 is still Oct 2 in New York.
        ny = Salon.objects.create(name="NY Salon", timezone="America/New_York")
        sale = self._completed_sale(salon=ny)
        refund = record_refund(sale, Decimal("20.00"), tender="cash")
        Refund.objects.filter(pk=refund.pk).update(
            created_at=self._at(self.day, hour=1)
        )
        self.assertEqual(refunds_by_day(ny, self.day).refund_count, 0)
        self.assertEqual(
            refunds_by_day(ny, self.day - datetime.timedelta(days=1)).total,
            Decimal("20.00"),
        )

    def test_read_only_and_missing_arguments(self):
        sale = self._completed_sale()
        self._refund(sale, "20.00")
        refunds_by_day(self.salon, self.day)
        refund_totals(self.salon, self.day, self.day)
        self.assertEqual(Refund.objects.count(), 1)
        with self.assertRaises(ValueError):
            refunds_by_day(None, self.day)
        with self.assertRaises(ValueError):
            refunds_by_day(self.salon, None)
        with self.assertRaises(ValueError):
            refund_totals(self.salon, self.day,
                          self.day - datetime.timedelta(days=1))
