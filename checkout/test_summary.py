import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Sale, SaleItem
from checkout.summary import daily_sales_summary
from saloncore.models import Salon


class DailySalesSummaryTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.day = datetime.date(2026, 10, 3)

    def _at(self, day, hour=12):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, 0)),
            datetime.timezone.utc,
        )

    def _sale(self, salon, items, status=Sale.Status.COMPLETED, day=None,
              completed=True):
        day = day or self.day
        sale = Sale.objects.create(salon=salon, status=status)
        for kind, price, qty in items:
            SaleItem.objects.create(
                sale=sale, kind=kind, description=kind,
                unit_price=Decimal(price), quantity=qty,
            )
        stamp = self._at(day)
        updates = {"created_at": stamp}
        if completed:
            updates["completed_at"] = stamp
        Sale.objects.filter(pk=sale.pk).update(**updates)
        sale.refresh_from_db()
        return sale

    def test_empty_day_is_zeros(self):
        result = daily_sales_summary(self.salon, self.day)
        self.assertEqual(result.sales_count, 0)
        self.assertEqual(result.count, 0)
        self.assertEqual(result.gross_total, Decimal("0.00"))
        self.assertEqual(result.total, Decimal("0.00"))
        self.assertEqual(result.service_total, Decimal("0.00"))
        self.assertEqual(result.retail_total, Decimal("0.00"))
        self.assertEqual(result.product_total, Decimal("0.00"))
        self.assertEqual(
            result.by_kind,
            {"service": Decimal("0.00"), "product": Decimal("0.00")},
        )
        self.assertEqual(result.item_count, 0)
        self.assertEqual(result.day, self.day)

    def test_multi_sale_totals_and_kind_split(self):
        self._sale(self.salon, [("service", "85.00", 1),
                                ("product", "20.00", 2)])
        self._sale(self.salon, [("service", "50.00", 1)])
        # A sale on another day must not leak into this day.
        self._sale(self.salon, [("service", "999.00", 1)],
                   day=self.day + datetime.timedelta(days=1))
        result = daily_sales_summary(self.salon, self.day)
        self.assertEqual(result.sales_count, 2)
        # 85 + (20*2) + 50 = 175; service 135, retail/product 40.
        self.assertEqual(result.gross_total, Decimal("175.00"))
        self.assertEqual(result.service_total, Decimal("135.00"))
        self.assertEqual(result.retail_total, Decimal("40.00"))
        self.assertEqual(result.by_kind["service"], Decimal("135.00"))
        self.assertEqual(result.by_kind["product"], Decimal("40.00"))
        self.assertEqual(result.item_count, 3)

    def test_cross_salon_isolation(self):
        self._sale(self.salon, [("service", "85.00", 1)])
        self._sale(self.other, [("service", "999.00", 1),
                                ("product", "999.00", 1)])
        result = daily_sales_summary(self.salon, self.day)
        self.assertEqual(result.sales_count, 1)
        self.assertEqual(result.gross_total, Decimal("85.00"))
        other = daily_sales_summary(self.other, self.day)
        self.assertEqual(other.sales_count, 1)
        self.assertEqual(other.gross_total, Decimal("1998.00"))

    def test_voided_sales_excluded(self):
        self._sale(self.salon, [("service", "85.00", 1)])
        self._sale(self.salon, [("service", "999.00", 1)],
                   status=Sale.Status.VOIDED)
        result = daily_sales_summary(self.salon, self.day)
        self.assertEqual(result.sales_count, 1)
        self.assertEqual(result.gross_total, Decimal("85.00"))

    def test_open_sale_counts_and_created_at_fallback(self):
        # No completed_at: the sale is attributed by created_at,
        # and a non-voided (open) sale is not excluded.
        self._sale(self.salon, [("product", "30.00", 1)],
                   status=Sale.Status.OPEN, completed=False)
        result = daily_sales_summary(self.salon, self.day)
        self.assertEqual(result.sales_count, 1)
        self.assertEqual(result.gross_total, Decimal("30.00"))
        self.assertEqual(result.retail_total, Decimal("30.00"))

    def test_completed_at_wins_over_created_at(self):
        sale = self._sale(
            self.salon, [("service", "60.00", 1)],
            day=self.day - datetime.timedelta(days=1),
        )
        Sale.objects.filter(pk=sale.pk).update(completed_at=self._at(self.day))
        self.assertEqual(
            daily_sales_summary(self.salon, self.day).gross_total,
            Decimal("60.00"),
        )
        yesterday = self.day - datetime.timedelta(days=1)
        self.assertEqual(
            daily_sales_summary(self.salon, yesterday).sales_count, 0
        )

    def test_read_only_records_nothing(self):
        self._sale(self.salon, [("service", "85.00", 1)])
        daily_sales_summary(self.salon, self.day)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(SaleItem.objects.count(), 1)

    def test_missing_arguments_raise(self):
        with self.assertRaises(ValueError):
            daily_sales_summary(None, self.day)
        with self.assertRaises(ValueError):
            daily_sales_summary(self.salon, None)
