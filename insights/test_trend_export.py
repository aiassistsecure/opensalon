import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.trend import daily_revenue_trend
from insights.trend_export import (
    TREND_FIELDNAMES,
    export_trend_csv,
    trend_csv,
)
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
END = date(2026, 11, 8)


class TrendExportCsvTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")

    def _sale(self, *, day_offset=0, salon=None):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED
        )
        stamp = datetime(2026, 11, 8, 12, 0, tzinfo=UTC) - timedelta(
            days=day_offset
        )
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp
        )
        sale.refresh_from_db()
        return sale

    def _item(self, sale, kind, price, quantity=1):
        return SaleItem.objects.create(
            sale=sale, kind=kind, quantity=quantity,
            unit_price=Decimal(price),
        )

    def _rows(self, salon=None, **kwargs):
        kwargs.setdefault("end_date", END)
        text = export_trend_csv(salon or self.salon, **kwargs)
        return list(csv.DictReader(io.StringIO(text)))

    def test_header(self):
        text = export_trend_csv(self.salon, days=3, end_date=END)
        header = list(csv.reader(io.StringIO(text)))[0]
        self.assertEqual(header, TREND_FIELDNAMES)
        self.assertEqual(TREND_FIELDNAMES, [
            "date", "service", "retail", "total", "moving_average_7d",
        ])

    def test_rows_match_service_output_and_ordering(self):
        today_sale = self._sale(day_offset=0)
        self._item(today_sale, SaleItem.Kind.SERVICE, "85.00")
        self._item(today_sale, SaleItem.Kind.PRODUCT, "24.00", quantity=2)
        yesterday = self._sale(day_offset=1)
        self._item(yesterday, SaleItem.Kind.SERVICE, "50.00")
        rows = self._rows(days=3)
        service_rows = daily_revenue_trend(
            self.salon, days=3, end_date=END
        )
        self.assertEqual(len(rows), len(service_rows))
        for csv_row, svc in zip(rows, service_rows):
            self.assertEqual(csv_row, {
                "date": svc.date.isoformat(),
                "service": str(svc.service),
                "retail": str(svc.retail),
                "total": str(svc.total),
                "moving_average_7d": str(svc.moving_average_7d),
            })
        # Oldest first, with exact delegated values.
        self.assertEqual(
            [r["date"] for r in rows],
            [(END - timedelta(days=2)).isoformat(),
             (END - timedelta(days=1)).isoformat(), END.isoformat()],
        )
        self.assertEqual(rows[-1]["total"], "133.00")
        self.assertEqual(rows[1]["total"], "50.00")
        self.assertEqual(rows[0]["total"], "0.00")

    def test_empty_range_is_header_only(self):
        text = export_trend_csv(self.salon, days=0, end_date=END)
        self.assertEqual(
            list(csv.reader(io.StringIO(text))), [TREND_FIELDNAMES]
        )
        self.assertEqual(self._rows(days=0), [])

    def test_zero_filled_days_match_service(self):
        rows = self._rows(days=3)
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["service"], "0.00")
            self.assertEqual(row["retail"], "0.00")
            self.assertEqual(row["total"], "0.00")
            self.assertEqual(row["moving_average_7d"], "0.00")

    def test_salon_scoping(self):
        other_sale = self._sale(salon=self.other)
        self._item(other_sale, SaleItem.Kind.SERVICE, "999.00")
        own_sale = self._sale()
        self._item(own_sale, SaleItem.Kind.SERVICE, "40.00")
        rows = self._rows(days=3)
        self.assertEqual(rows[-1]["total"], "40.00")
        self.assertEqual(
            sum(Decimal(r["total"]) for r in rows), Decimal("40.00")
        )
        other_rows = self._rows(salon=self.other, days=3)
        self.assertEqual(other_rows[-1]["total"], "999.00")

    def test_alias(self):
        text = trend_csv(self.salon, days=1, end_date=END)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], END.isoformat())

    def test_read_only(self):
        self._sale()
        before = Sale.objects.count()
        export_trend_csv(self.salon, days=3, end_date=END)
        self.assertEqual(Sale.objects.count(), before)
