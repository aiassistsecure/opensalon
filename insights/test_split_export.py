import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.services import last_7_days_revenue_split
from insights.split_export import (
    SPLIT_FIELDNAMES,
    export_split_csv,
    split_csv,
)
from saloncore.models import Salon

TODAY = date(2026, 11, 8)


class SplitExportCsvTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")

    def _sale(self, salon=None, *, status=Sale.Status.COMPLETED, when=None):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=status
        )
        stamp = when or datetime(2026, 11, 8, 12, 0, tzinfo=ZoneInfo("UTC"))
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
        kwargs.setdefault("today", TODAY)
        text = export_split_csv(salon or self.salon, **kwargs)
        return list(csv.DictReader(io.StringIO(text)))

    def test_header(self):
        self._item(self._sale(), SaleItem.Kind.SERVICE, "10.00")
        text = export_split_csv(self.salon, today=TODAY)
        header = list(csv.reader(io.StringIO(text)))[0]
        self.assertEqual(header, SPLIT_FIELDNAMES)
        self.assertEqual(SPLIT_FIELDNAMES, [
            "start_date", "end_date", "days",
            "service", "retail", "total",
        ])
        # No series column: the service carries no series field.
        self.assertNotIn("series", SPLIT_FIELDNAMES)

    def test_row_matches_service_output(self):
        sale = self._sale()
        self._item(sale, SaleItem.Kind.SERVICE, "85.00")
        self._item(sale, SaleItem.Kind.PRODUCT, "24.00", quantity=2)
        result = last_7_days_revenue_split(self.salon, today=TODAY)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {
            "start_date": result.start_date.isoformat(),
            "end_date": result.end_date.isoformat(),
            "days": str(result.days),
            "service": str(result.service.quantize(Decimal("0.01"))),
            "retail": str(result.retail.quantize(Decimal("0.01"))),
            "total": str(result.total.quantize(Decimal("0.01"))),
        })
        self.assertEqual(rows[0]["total"], "133.00")
        self.assertEqual(
            result.start_date, TODAY - timedelta(days=6)
        )

    def test_salon_isolation(self):
        other_sale = self._sale(salon=self.other)
        self._item(other_sale, SaleItem.Kind.SERVICE, "999.00")
        own_sale = self._sale()
        self._item(own_sale, SaleItem.Kind.SERVICE, "40.00")
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total"], "40.00")
        other_rows = self._rows(salon=self.other)
        self.assertEqual(other_rows[0]["total"], "999.00")

    def test_empty_is_header_only(self):
        result = last_7_days_revenue_split(self.salon, today=TODAY)
        self.assertEqual(result.total, Decimal("0.00"))
        text = export_split_csv(self.salon, today=TODAY)
        self.assertEqual(
            list(csv.reader(io.StringIO(text))), [SPLIT_FIELDNAMES]
        )
        self.assertEqual(self._rows(), [])

    def test_alias(self):
        self._item(self._sale(), SaleItem.Kind.SERVICE, "10.00")
        rows = list(csv.DictReader(io.StringIO(
            split_csv(self.salon, today=TODAY)
        )))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["service"], "10.00")

    def test_read_only(self):
        self._sale()
        before = Sale.objects.count()
        export_split_csv(self.salon, today=TODAY)
        self.assertEqual(Sale.objects.count(), before)
