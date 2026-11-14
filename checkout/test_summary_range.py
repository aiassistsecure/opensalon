import datetime
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from checkout.models import Sale, SaleItem
from checkout.summary import daily_sales_summaries, daily_sales_summary
from saloncore.models import Salon


class DailySalesSummariesParityTests(TestCase):
    """The range reader must equal the daily reader, day by day."""

    def setUp(self):
        # A non-UTC salon, so local-day bucketing is exercised:
        # America/New_York is UTC-4 in October (EDT).
        self.salon = Salon.objects.create(
            name="Example Salon", timezone="America/New_York"
        )
        self.start = datetime.date(2026, 10, 2)
        self.end = datetime.date(2026, 10, 5)
        self.days = [
            self.start + datetime.timedelta(days=i) for i in range(4)
        ]
        self._seed()

    def _utc(self, day, hour):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, 0)),
            datetime.timezone.utc,
        )

    def _sale(self, items, status=Sale.Status.COMPLETED, completed_at=None,
              created_at=None, sale_discount="0.00"):
        sale = Sale.objects.create(salon=self.salon, status=status)
        for kind, price, qty, discount in items:
            SaleItem.objects.create(
                sale=sale, kind=kind, description=kind,
                unit_price=Decimal(price), quantity=qty,
                discount_amount=Decimal(discount),
            )
        updates = {}
        if created_at is not None:
            updates["created_at"] = created_at
        if completed_at is not None:
            updates["completed_at"] = completed_at
        if Decimal(sale_discount):
            updates["discount_amount"] = Decimal(sale_discount)
        if updates:
            Sale.objects.filter(pk=sale.pk).update(**updates)
        sale.refresh_from_db()
        return sale

    def _seed(self):
        d = self.days
        # Oct 2 local: completed Oct 3 01:30 UTC = Oct 2 21:30 EDT.
        # All three kinds, an item discount, and a sale discount.
        self._sale(
            [
                ("service", "85.00", 1, "10.00"),
                ("product", "20.00", 2, "0.00"),
                ("series", "100.00", 1, "0.00"),
            ],
            completed_at=self._utc(d[1], 1) + datetime.timedelta(minutes=30),
            sale_discount="5.00",
        )
        # Oct 3 local: a plain completed sale.
        self._sale(
            [("service", "50.00", 1, "0.00"),
             ("series", "100.00", 2, "0.00")],
            completed_at=self._utc(d[1], 15),
        )
        # Oct 3 local: completed_at NULL — attributed by created_at.
        self._sale(
            [("product", "30.00", 1, "0.00")],
            status=Sale.Status.OPEN,
            created_at=self._utc(d[1], 18),
        )
        # Oct 3 local: voided — excluded everywhere.
        self._sale(
            [("service", "999.00", 1, "0.00")],
            status=Sale.Status.VOIDED,
            completed_at=self._utc(d[1], 16),
        )
        # Oct 4 local: intentionally empty.
        # Oct 5 local: one sale with an item discount only.
        self._sale(
            [("service", "60.00", 1, "2.50")],
            completed_at=self._utc(d[3], 12),
        )

    def test_range_matches_daily_day_by_day(self):
        result = daily_sales_summaries(self.salon, self.start, self.end)
        expected = [daily_sales_summary(self.salon, d) for d in self.days]
        self.assertEqual([s.day for s in result], self.days)
        fields = (
            "sales_count", "gross_total", "service_total", "retail_total",
            "series_total", "discount_total", "net_total", "by_kind",
            "item_count",
        )
        for got, want in zip(result, expected):
            for name in fields:
                self.assertEqual(
                    getattr(got, name), getattr(want, name),
                    f"{got.day} field {name}",
                )
        self.assertEqual(result, expected)

    def test_seeded_figures_are_the_expected_ones(self):
        result = daily_sales_summaries(self.salon, self.start, self.end)
        by_day = {s.day: s for s in result}
        oct2 = by_day[self.days[0]]
        self.assertEqual(oct2.sales_count, 1)
        self.assertEqual(oct2.gross_total, Decimal("225.00"))
        self.assertEqual(oct2.discount_total, Decimal("15.00"))
        self.assertEqual(oct2.net_total, Decimal("210.00"))
        oct3 = by_day[self.days[1]]
        self.assertEqual(oct3.sales_count, 2)
        self.assertEqual(oct3.gross_total, Decimal("280.00"))
        self.assertEqual(oct3.series_total, Decimal("200.00"))
        oct4 = by_day[self.days[2]]
        self.assertEqual(oct4.sales_count, 0)
        self.assertEqual(oct4.gross_total, Decimal("0.00"))
        oct5 = by_day[self.days[3]]
        self.assertEqual(oct5.sales_count, 1)
        self.assertEqual(oct5.discount_total, Decimal("2.50"))

    def test_no_subquery_in_items_read(self):
        with CaptureQueriesContext(connection) as captured:
            daily_sales_summary(self.salon, self.days[0])
            daily_sales_summaries(self.salon, self.start, self.end)
        self.assertTrue(captured.captured_queries)
        for query in captured.captured_queries:
            self.assertNotIn("IN (SELECT", query["sql"].upper())
