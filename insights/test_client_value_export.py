import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from checkout.models import Sale, SaleItem
from clients.models import Client
from insights.client_value import client_value
from insights.client_value_export import (
    CLIENT_VALUE_FIELDNAMES,
    export_client_value_csv,
)
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)


class ClientValueExportCsvTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.alice = Client.objects.create(
            salon=self.salon, first_name="Alice", last_name="Able"
        )
        self.bob = Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Baker"
        )

    def _sale(self, client=None, *, day, price="50.00",
              status=Sale.Status.COMPLETED):
        sale = Sale.objects.create(
            salon=self.salon, client=client, status=status
        )
        stamp = datetime(2026, 11, 2, 12, 0, tzinfo=UTC) + timedelta(days=day)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp
        )
        if price is not None:
            SaleItem.objects.create(
                sale=sale, kind=SaleItem.Kind.SERVICE,
                quantity=1, unit_price=Decimal(price),
            )
        return sale

    def _rows(self, **kw):
        text = export_client_value_csv(self.salon, START, END, **kw)
        return list(csv.DictReader(io.StringIO(text)))

    def test_header_only_when_empty(self):
        text = export_client_value_csv(self.salon, START, END)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows, [CLIENT_VALUE_FIELDNAMES])
        self.assertEqual(
            CLIENT_VALUE_FIELDNAMES,
            ["client_id", "client_name", "salon_id", "total", "sale_count"],
        )

    def test_row_values_match_service_and_ordering(self):
        self._sale(self.alice, day=0, price="60.00")
        self._sale(self.alice, day=1, price="40.00")  # 100.00, 2 sales
        self._sale(self.bob, day=0, price="150.00")  # 150.00, 1 sale
        self._sale(None, day=1, price="30.00")  # unattributed: no row
        self._sale(self.bob, day=1, status=Sale.Status.OPEN, price="999.00")
        result = client_value(self.salon, START, END)
        rows = self._rows()
        self.assertEqual(len(rows), len(result.rows))
        for csv_row, svc_row in zip(rows, result.rows):
            self.assertEqual(int(csv_row["client_id"]), svc_row.client_id)
            self.assertEqual(csv_row["client_name"], svc_row.display_name)
            self.assertEqual(int(csv_row["salon_id"]), self.salon.pk)
            self.assertEqual(Decimal(csv_row["total"]), svc_row.total)
            self.assertEqual(int(csv_row["sale_count"]), svc_row.sale_count)
        # Service ordering preserved: Bob (150) before Alice (100).
        self.assertEqual(
            [r["client_name"] for r in rows], ["Bob Baker", "Alice Able"]
        )
        self.assertEqual(rows[1]["total"], "100.00")

    def test_read_only(self):
        self._sale(self.alice, day=0)
        before = Sale.objects.count()
        export_client_value_csv(self.salon, START, END)
        self.assertEqual(Sale.objects.count(), before)
