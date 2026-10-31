import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Payment, Sale, SaleItem
from checkout.summary import daily_sales_summary
from checkout.tender_totals import tender_totals
from checkout.void import void_sale
from saloncore.models import Salon


class VoidSaleTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.day = timezone.localdate()

    def _completed_sale(self, price="85.00"):
        sale = Sale.objects.create(
            salon=self.salon,
            status=Sale.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal(price),
        )
        Payment.objects.create(
            sale=sale, method=Payment.Method.CASH,
            amount=Decimal(price), status=Payment.Status.COMPLETED,
        )
        return sale

    def test_void_completed_sale_records_status_reason_and_timestamp(self):
        sale = self._completed_sale()
        before = timezone.now()
        result = void_sale(sale, "  rung up twice  ")
        after = timezone.now()
        self.assertIs(result, sale)
        self.assertEqual(result.status, Sale.Status.VOIDED)
        self.assertEqual(result.void_reason, "rung up twice")
        self.assertIsNotNone(result.voided_at)
        self.assertLessEqual(before, result.voided_at)
        self.assertLessEqual(result.voided_at, after)
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.VOIDED)
        self.assertEqual(sale.void_reason, "rung up twice")
        self.assertEqual(sale.voided_at, result.voided_at)

    def test_void_preserves_sale_items_and_payments(self):
        sale = self._completed_sale()
        void_sale(sale, "client disputed")
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(SaleItem.objects.filter(sale=sale).count(), 1)
        self.assertEqual(Payment.objects.filter(sale=sale).count(), 1)
        sale.refresh_from_db()
        self.assertEqual(sale.total, Decimal("85.00"))

    def test_voided_sale_excluded_from_daily_summary(self):
        kept = self._completed_sale("50.00")
        voided = self._completed_sale("85.00")
        void_sale(voided, "entered in error")
        result = daily_sales_summary(self.salon, self.day)
        self.assertEqual(result.sales_count, 1)
        self.assertEqual(result.gross_total, Decimal("50.00"))
        self.assertEqual(result.service_total, Decimal("50.00"))
        self.assertEqual(kept.status, Sale.Status.COMPLETED)

    def test_voided_sale_excluded_from_tender_totals(self):
        self._completed_sale("50.00")
        void_sale(self._completed_sale("999.00"), "entered in error")
        now = timezone.now()
        result = tender_totals(
            now - datetime.timedelta(hours=1),
            now + datetime.timedelta(hours=1),
            salon=self.salon,
        )
        self.assertEqual(result.total, Decimal("50.00"))
        self.assertEqual(result.count, 1)
        self.assertEqual(result.by_method["cash"], Decimal("50.00"))

    def test_void_open_sale_raises_and_changes_nothing(self):
        sale = Sale.objects.create(salon=self.salon, status=Sale.Status.OPEN)
        with self.assertRaises(ValueError):
            void_sale(sale, "no longer wanted")
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.OPEN)
        self.assertEqual(sale.void_reason, "")
        self.assertIsNone(sale.voided_at)

    def test_void_already_voided_raises_and_preserves_first_void(self):
        sale = self._completed_sale()
        void_sale(sale, "first reason")
        first_at = sale.voided_at
        with self.assertRaises(ValueError):
            void_sale(sale, "second reason")
        sale.refresh_from_db()
        self.assertEqual(sale.void_reason, "first reason")
        self.assertEqual(sale.voided_at, first_at)

    def test_void_requires_a_reason(self):
        for bad in (None, "", "   "):
            sale = self._completed_sale()
            with self.assertRaises(ValueError):
                void_sale(sale, bad)
            sale.refresh_from_db()
            self.assertEqual(sale.status, Sale.Status.COMPLETED)
            self.assertIsNone(sale.voided_at)

    def test_void_requires_a_sale(self):
        with self.assertRaises(ValueError):
            void_sale(None, "entered in error")
