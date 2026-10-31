import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from checkout.models import Sale, SaleItem
from clients.models import Client
from insights.returning import new_vs_returning_revenue
from insights.returning_export import (
    RETURNING_FIELDNAMES,
    export_returning_revenue_csv,
    returning_revenue_csv,
)
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)


class ReturningExportCsvTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.returning_client = Client.objects.create(
            salon=self.salon, first_name="Ret", last_name="Urning"
        )
        self.new_client = Client.objects.create(
            salon=self.salon, first_name="New", last_name="Client"
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
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE,
            quantity=1, unit_price=Decimal(price),
        )
        return sale

    def _rows(self, start=START, end=END, **kwargs):
        text = export_returning_revenue_csv(
            self.salon, start, end, **kwargs
        )
        return list(csv.DictReader(io.StringIO(text)))

    def test_header(self):
        text = export_returning_revenue_csv(self.salon, START, END)
        header = list(csv.reader(io.StringIO(text)))[0]
        self.assertEqual(header, RETURNING_FIELDNAMES)
        self.assertEqual(RETURNING_FIELDNAMES, [
            "start_date", "end_date", "returning_revenue",
            "new_revenue", "unattributed_revenue", "total",
            "returning_sale_count", "new_sale_count",
            "unattributed_sale_count",
        ])

    def test_row_matches_service_output(self):
        # Returning: completed sale a week before the window.
        self._sale(self.returning_client, day=-7, price="999.00")
        self._sale(self.returning_client, day=1, price="85.00")
        self._sale(self.returning_client, day=2, price="15.00")
        # New: first-ever sale is inside the window.
        self._sale(self.new_client, day=0, price="50.00")
        self._sale(self.new_client, day=3, price="10.00")
        # Unattributed: no client link at all.
        self._sale(None, day=1, price="30.00")

        result = new_vs_returning_revenue(self.salon, START, END)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["start_date"], result.start_date.isoformat())
        self.assertEqual(row["end_date"], result.end_date.isoformat())
        self.assertEqual(
            row["returning_revenue"], str(result.returning_revenue)
        )
        self.assertEqual(row["new_revenue"], str(result.new_revenue))
        self.assertEqual(
            row["unattributed_revenue"],
            str(result.unattributed_revenue),
        )
        self.assertEqual(row["total"], str(result.total))
        self.assertEqual(
            int(row["returning_sale_count"]), result.returning_sale_count
        )
        self.assertEqual(int(row["new_sale_count"]), result.new_sale_count)
        self.assertEqual(
            int(row["unattributed_sale_count"]),
            result.unattributed_sale_count,
        )
        # Concrete fixture expectations.
        self.assertEqual(
            (row["returning_revenue"], row["new_revenue"],
             row["unattributed_revenue"], row["total"]),
            ("100.00", "60.00", "30.00", "190.00"),
        )
        self.assertEqual(
            (int(row["returning_sale_count"]), int(row["new_sale_count"]),
             int(row["unattributed_sale_count"])),
            (2, 2, 1),
        )

    def test_alias(self):
        self._sale(self.new_client, day=0, price="50.00")
        text = returning_revenue_csv(self.salon, START, END)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["new_revenue"], "50.00")

    def test_empty_and_reversed_windows_are_single_zero_rows(self):
        for start, end in ((START, END), (END, START)):
            result = new_vs_returning_revenue(self.salon, start, end)
            rows = self._rows(start, end)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(
                row["start_date"], result.start_date.isoformat()
            )
            self.assertEqual(row["end_date"], result.end_date.isoformat())
            self.assertEqual(row["returning_revenue"], "0.00")
            self.assertEqual(row["new_revenue"], "0.00")
            self.assertEqual(row["unattributed_revenue"], "0.00")
            self.assertEqual(row["total"], "0.00")
            self.assertEqual(int(row["returning_sale_count"]), 0)
            self.assertEqual(int(row["new_sale_count"]), 0)
            self.assertEqual(int(row["unattributed_sale_count"]), 0)

    def test_read_only(self):
        self._sale(self.new_client, day=0)
        before = (Sale.objects.count(), SaleItem.objects.count())
        export_returning_revenue_csv(self.salon, START, END)
        self.assertEqual(
            (Sale.objects.count(), SaleItem.objects.count()), before
        )
