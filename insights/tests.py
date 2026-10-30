from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Sale, SaleItem
from insights.services import RevenueSplit, last_7_days_revenue_split
from saloncore.models import Salon


class Last7DaysRevenueSplitTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.today = timezone.now().date()

    def _sale(self, salon=None, *, status=Sale.Status.COMPLETED, when=None,
              completed=True):
        sale = Sale.objects.create(salon=salon or self.salon, status=status)
        stamp = when or timezone.now()
        updates = {"created_at": stamp}
        if completed:
            updates["completed_at"] = stamp
        Sale.objects.filter(pk=sale.pk).update(**updates)
        sale.refresh_from_db()
        return sale

    def _item(self, sale, kind, price, quantity=1):
        return SaleItem.objects.create(
            sale=sale, kind=kind, quantity=quantity,
            unit_price=Decimal(price),
        )

    def test_split_service_vs_retail_with_quantities(self):
        sale = self._sale()
        self._item(sale, SaleItem.Kind.SERVICE, "85.00")
        self._item(sale, SaleItem.Kind.PRODUCT, "24.00", quantity=2)
        result = last_7_days_revenue_split(self.salon, today=self.today)
        self.assertIsInstance(result, RevenueSplit)
        self.assertEqual(result.service, Decimal("85.00"))
        self.assertEqual(result.retail, Decimal("48.00"))
        self.assertEqual(result.total, Decimal("133.00"))
        self.assertEqual(result.end_date, self.today)
        self.assertEqual(result.start_date, self.today - timedelta(days=6))
        self.assertEqual(result.days, 7)

    def test_no_sales_returns_zeroes_not_none(self):
        result = last_7_days_revenue_split(self.salon, today=self.today)
        self.assertEqual(result.service, Decimal("0.00"))
        self.assertEqual(result.retail, Decimal("0.00"))
        self.assertEqual(result.total, Decimal("0.00"))

    def test_window_includes_day_7_boundary_and_excludes_older(self):
        edge = self._sale(when=timezone.now() - timedelta(days=6))
        self._item(edge, SaleItem.Kind.SERVICE, "50.00")
        old = self._sale(when=timezone.now() - timedelta(days=7))
        self._item(old, SaleItem.Kind.SERVICE, "999.00")
        result = last_7_days_revenue_split(self.salon, today=self.today)
        self.assertEqual(result.service, Decimal("50.00"))

    def test_open_and_voided_sales_excluded(self):
        for status in (Sale.Status.OPEN, Sale.Status.VOIDED):
            sale = self._sale(status=status)
            self._item(sale, SaleItem.Kind.PRODUCT, "10.00")
        result = last_7_days_revenue_split(self.salon, today=self.today)
        self.assertEqual(result.total, Decimal("0.00"))

    def test_other_salon_sales_excluded(self):
        sale = self._sale(salon=self.other)
        self._item(sale, SaleItem.Kind.SERVICE, "70.00")
        result = last_7_days_revenue_split(self.salon, today=self.today)
        self.assertEqual(result.total, Decimal("0.00"))

    def test_completed_sale_without_completed_at_uses_created_at(self):
        sale = self._sale(completed=False)
        Sale.objects.filter(pk=sale.pk).update(completed_at=None)
        self._item(sale, SaleItem.Kind.SERVICE, "40.00")
        result = last_7_days_revenue_split(self.salon, today=self.today)
        self.assertEqual(result.service, Decimal("40.00"))
