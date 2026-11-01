import csv
import datetime
import io
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from checkout.models import Sale, SaleItem
from checkout.summary import daily_sales_summary
from checkout.summary_export import (
    EXPORT_FIELDNAMES,
    export_summary,
    export_summary_csv,
    summary_csv,
)
from saloncore.models import Salon


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


class SummaryExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.day = datetime.date(2026, 10, 3)

    def _at(self, day, hour=12):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, 0)),
            datetime.timezone.utc,
        )

    def _sale(self, salon, items, day=None, status=Sale.Status.COMPLETED):
        day = day or self.day
        sale = Sale.objects.create(salon=salon, status=status)
        for kind, price, qty in items:
            SaleItem.objects.create(
                sale=sale, kind=kind, description=kind,
                unit_price=Decimal(price), quantity=qty,
            )
        stamp = self._at(day)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        return sale

    def test_csv_header_and_row_keys(self):
        text = export_summary_csv(self.salon, self.day)
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        rows = export_summary(self.salon, self.day)
        self.assertEqual(len(rows), 1)
        for row in rows:
            self.assertEqual(list(row), EXPORT_FIELDNAMES)
        self.assertEqual(list(_rows(text)[0]), EXPORT_FIELDNAMES)

    def test_row_values_match_service_output(self):
        self._sale(self.salon, [("service", "85.00", 1),
                                ("product", "20.00", 2)])
        self._sale(self.salon, [("service", "50.00", 1)])
        summary = daily_sales_summary(self.salon, self.day)
        rows = export_summary(self.salon, self.day)
        self.assertEqual(rows, [{
            "salon_id": self.salon.pk,
            "date": self.day.isoformat(),
            "sales_count": summary.sales_count,
            "gross_total": str(summary.gross_total.quantize(Decimal("0.01"))),
            "service_total": str(
                summary.service_total.quantize(Decimal("0.01"))),
            "retail_total": str(summary.retail_total.quantize(Decimal("0.01"))),
            "series_total": str(summary.series_total.quantize(Decimal("0.01"))),
            "item_count": summary.item_count,
        }])
        self.assertEqual(summary.gross_total, Decimal("175.00"))

    def test_delegates_to_daily_sales_summary_per_day(self):
        last = self.day + datetime.timedelta(days=2)
        with mock.patch(
            "checkout.summary_export.daily_sales_summary",
            wraps=daily_sales_summary,
        ) as spy:
            rows = export_summary(self.salon, self.day, last)
        self.assertEqual(
            [call.args[1] for call in spy.call_args_list],
            [self.day + datetime.timedelta(days=n) for n in range(3)],
        )
        self.assertTrue(all(call.args[0] == self.salon
                            for call in spy.call_args_list))
        self.assertEqual([r["date"] for r in rows],
                         [(self.day + datetime.timedelta(days=n)).isoformat()
                          for n in range(3)])

    def test_csv_agrees_with_list_and_alias(self):
        self._sale(self.salon, [("service", "85.00", 1)])
        text = export_summary_csv(self.salon, self.day)
        parsed = [{
            **r,
            "salon_id": int(r["salon_id"]),
            "sales_count": int(r["sales_count"]),
            "item_count": int(r["item_count"]),
        } for r in _rows(text)]
        self.assertEqual(parsed, export_summary(self.salon, self.day))
        self.assertEqual(summary_csv(self.salon, self.day), text)

    def test_empty_range_zero_rows_and_reversed_is_empty(self):
        last = self.day + datetime.timedelta(days=1)
        rows = export_summary(self.salon, self.day, last)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["sales_count"], 0)
            self.assertEqual(row["gross_total"], "0.00")
            self.assertEqual(row["service_total"], "0.00")
            self.assertEqual(row["retail_total"], "0.00")
            self.assertEqual(row["series_total"], "0.00")
            self.assertEqual(row["item_count"], 0)
        self.assertEqual(export_summary(self.salon, last, self.day), [])
        text = export_summary_csv(self.salon, last, self.day)
        self.assertEqual(text, ",".join(EXPORT_FIELDNAMES) + "\n")
        self.assertEqual(export_summary(None, self.day), [])
        self.assertEqual(export_summary(self.salon, None), [])

    def test_salon_isolation(self):
        self._sale(self.salon, [("service", "85.00", 1)])
        self._sale(self.other, [("service", "999.00", 1),
                                ("product", "999.00", 1)])
        rows = export_summary(self.salon, self.day)
        summary = daily_sales_summary(self.salon, self.day)
        self.assertEqual(rows[0]["salon_id"], self.salon.pk)
        self.assertEqual(Decimal(rows[0]["gross_total"]), summary.gross_total)
        self.assertEqual(rows[0]["gross_total"], "85.00")
        self.assertEqual(rows[0]["sales_count"], 1)
        parsed = _rows(export_summary_csv(self.salon, self.day))
        self.assertEqual([r["salon_id"] for r in parsed],
                         [str(self.salon.pk)])

    def test_series_total_column_matches_service(self):
        self.assertIn("series_total", EXPORT_FIELDNAMES)
        self._sale(self.salon, [("service", "85.00", 1),
                                ("product", "20.00", 2),
                                ("series", "100.00", 2)])
        summary = daily_sales_summary(self.salon, self.day)
        rows = export_summary(self.salon, self.day)
        self.assertEqual(rows[0]["series_total"], "200.00")
        self.assertEqual(
            Decimal(rows[0]["series_total"]), summary.series_total)
        self.assertEqual(rows[0]["gross_total"], "325.00")
        self.assertEqual(
            Decimal(rows[0]["gross_total"]),
            Decimal(rows[0]["service_total"])
            + Decimal(rows[0]["retail_total"])
            + Decimal(rows[0]["series_total"]),
        )
        parsed = _rows(export_summary_csv(self.salon, self.day))
        self.assertEqual(parsed[0]["series_total"], "200.00")

    def test_series_only_sale_exports_series_column(self):
        self._sale(self.salon, [("series", "200.00", 1)])
        rows = export_summary(self.salon, self.day)
        self.assertEqual(rows[0]["series_total"], "200.00")
        self.assertEqual(rows[0]["gross_total"], "200.00")

    def test_read_only_records_unchanged(self):
        self._sale(self.salon, [("service", "85.00", 1)])
        before = (Sale.objects.count(), SaleItem.objects.count())
        export_summary(self.salon, self.day)
        export_summary_csv(self.salon, self.day)
        self.assertEqual((Sale.objects.count(), SaleItem.objects.count()),
                         before)
