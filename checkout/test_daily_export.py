import csv
import datetime
import io
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from checkout.daily_export import (
    EXPORT_FIELDNAMES,
    daily_sales_csv,
    export_daily_sales,
    export_daily_sales_csv,
)
from checkout.models import Sale, SaleItem
from checkout.summary import daily_sales_summary
from checkout.summary_export import (
    EXPORT_FIELDNAMES as SUMMARY_FIELDNAMES,
)
from checkout.summary_export import export_summary, export_summary_csv
from saloncore.models import Salon


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


class DailyExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.day = datetime.date(2026, 10, 3)

    def _at(self, day, hour=12):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, 0)),
            datetime.timezone.utc,
        )

    def _sale(self, salon, items, day=None, status=Sale.Status.COMPLETED,
              sale_discount="0.00"):
        day = day or self.day
        sale = Sale.objects.create(
            salon=salon, status=status,
            discount_amount=Decimal(sale_discount))
        for item in items:
            kind, price, qty = item[:3]
            discount = item[3] if len(item) > 3 else "0.00"
            SaleItem.objects.create(
                sale=sale, kind=kind, description=kind,
                unit_price=Decimal(price), quantity=qty,
                discount_amount=Decimal(discount),
            )
        stamp = self._at(day)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        return sale

    def test_csv_header_and_row_keys(self):
        text = export_daily_sales_csv(self.salon, self.day)
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        rows = export_daily_sales(self.salon, self.day)
        self.assertEqual(len(rows), 1)
        for row in rows:
            self.assertEqual(list(row), EXPORT_FIELDNAMES)
        self.assertEqual(list(_rows(text)[0]), EXPORT_FIELDNAMES)

    def test_row_values_match_service_output(self):
        self._sale(self.salon, [("service", "85.00", 1),
                                ("product", "20.00", 2)])
        self._sale(self.salon, [("service", "50.00", 1)])
        summary = daily_sales_summary(self.salon, self.day)
        rows = export_daily_sales(self.salon, self.day)
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
            "discount_total": str(
                summary.discount_total.quantize(Decimal("0.01"))),
            "net_total": str(summary.net_total.quantize(Decimal("0.01"))),
        }])
        self.assertEqual(summary.gross_total, Decimal("175.00"))
        self.assertEqual(summary.service_total, Decimal("135.00"))
        self.assertEqual(summary.retail_total, Decimal("40.00"))

    def test_delegates_to_daily_sales_summary_per_day(self):
        last = self.day + datetime.timedelta(days=2)
        with mock.patch(
            "checkout.daily_export.daily_sales_summary",
            wraps=daily_sales_summary,
        ) as spy:
            rows = export_daily_sales(self.salon, self.day, last)
        self.assertEqual(
            [call.args[1] for call in spy.call_args_list],
            [self.day + datetime.timedelta(days=n) for n in range(3)],
        )
        self.assertTrue(all(call.args[0] == self.salon
                            for call in spy.call_args_list))
        self.assertEqual([r["date"] for r in rows],
                         [d.isoformat() for d in
                          (self.day + datetime.timedelta(days=n)
                           for n in range(3))])

    def test_csv_agrees_with_list_and_alias(self):
        self._sale(self.salon, [("service", "85.00", 1)])
        text = export_daily_sales_csv(self.salon, self.day)
        parsed = [{
            **r,
            "salon_id": int(r["salon_id"]),
            "sales_count": int(r["sales_count"]),
            "item_count": int(r["item_count"]),
        } for r in _rows(text)]
        self.assertEqual(parsed, export_daily_sales(self.salon, self.day))
        self.assertEqual(daily_sales_csv(self.salon, self.day), text)

    def test_empty_range_zero_rows_and_reversed_is_empty(self):
        last = self.day + datetime.timedelta(days=1)
        rows = export_daily_sales(self.salon, self.day, last)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["sales_count"], 0)
            self.assertEqual(row["gross_total"], "0.00")
            self.assertEqual(row["service_total"], "0.00")
            self.assertEqual(row["retail_total"], "0.00")
            self.assertEqual(row["series_total"], "0.00")
            self.assertEqual(row["item_count"], 0)
            self.assertEqual(row["discount_total"], "0.00")
            self.assertEqual(row["net_total"], "0.00")
        self.assertEqual(export_daily_sales(self.salon, last, self.day), [])
        text = export_daily_sales_csv(self.salon, last, self.day)
        self.assertEqual(text, ",".join(EXPORT_FIELDNAMES) + "\n")
        self.assertEqual(export_daily_sales(None, self.day), [])
        self.assertEqual(export_daily_sales(self.salon, None), [])

    def test_range_boundaries_inclusive(self):
        before = self.day - datetime.timedelta(days=1)
        after = self.day + datetime.timedelta(days=1)
        self._sale(self.salon, [("service", "10.00", 1)], day=before)
        self._sale(self.salon, [("service", "85.00", 1)], day=self.day)
        self._sale(self.salon, [("product", "30.00", 1)], day=after)
        self._sale(self.salon, [("service", "999.00", 1)],
                   day=after + datetime.timedelta(days=1))
        rows = export_daily_sales(self.salon, before, after)
        self.assertEqual([r["date"] for r in rows],
                         [before.isoformat(), self.day.isoformat(),
                          after.isoformat()])
        self.assertEqual([r["gross_total"] for r in rows],
                         ["10.00", "85.00", "30.00"])
        self.assertEqual([r["sales_count"] for r in rows], [1, 1, 1])

    def test_salon_scoping_matches_service(self):
        self._sale(self.salon, [("service", "85.00", 1)])
        self._sale(self.other, [("service", "999.00", 1),
                                ("product", "999.00", 1)])
        rows = export_daily_sales(self.salon, self.day)
        summary = daily_sales_summary(self.salon, self.day)
        self.assertEqual(rows[0]["salon_id"], self.salon.pk)
        self.assertEqual(Decimal(rows[0]["gross_total"]), summary.gross_total)
        self.assertEqual(rows[0]["gross_total"], "85.00")
        self.assertEqual(rows[0]["sales_count"], 1)
        parsed = _rows(export_daily_sales_csv(self.salon, self.day))
        self.assertEqual([r["salon_id"] for r in parsed],
                         [str(self.salon.pk)])

    def test_series_total_column_matches_service(self):
        self.assertIn("series_total", EXPORT_FIELDNAMES)
        self._sale(self.salon, [("service", "85.00", 1),
                                ("product", "20.00", 2),
                                ("series", "100.00", 2)])
        summary = daily_sales_summary(self.salon, self.day)
        rows = export_daily_sales(self.salon, self.day)
        self.assertEqual(rows[0]["series_total"], "200.00")
        self.assertEqual(
            Decimal(rows[0]["series_total"]), summary.series_total)
        self.assertEqual(rows[0]["gross_total"], "325.00")
        parsed = _rows(export_daily_sales_csv(self.salon, self.day))
        self.assertEqual(parsed[0]["series_total"], "200.00")

    def test_discount_and_net_columns_appended(self):
        self.assertEqual(
            EXPORT_FIELDNAMES[-2:], ["discount_total", "net_total"])
        self.assertEqual(EXPORT_FIELDNAMES, SUMMARY_FIELDNAMES)

    def test_discounted_sale_export_matches_summary(self):
        # Gross 85 + 20*2 = 125; discounts 10 (line) + 8 (line)
        # + 5 (whole-sale) = 23; net = 125 - 23 = 102.
        self._sale(
            self.salon,
            [("service", "85.00", 1, "10.00"),
             ("product", "20.00", 2, "8.00")],
            sale_discount="5.00")
        summary = daily_sales_summary(self.salon, self.day)
        self.assertEqual(summary.discount_total, Decimal("23.00"))
        self.assertEqual(summary.net_total, Decimal("102.00"))
        rows = export_daily_sales(self.salon, self.day)
        self.assertEqual(
            rows[0]["discount_total"],
            str(summary.discount_total.quantize(Decimal("0.01"))))
        self.assertEqual(
            rows[0]["net_total"],
            str(summary.net_total.quantize(Decimal("0.01"))))
        self.assertEqual(rows[0]["discount_total"], "23.00")
        self.assertEqual(rows[0]["net_total"], "102.00")
        self.assertEqual(
            Decimal(rows[0]["net_total"]),
            Decimal(rows[0]["gross_total"])
            - Decimal(rows[0]["discount_total"]))
        parsed = _rows(export_daily_sales_csv(self.salon, self.day))
        self.assertEqual(parsed[0]["discount_total"], "23.00")
        self.assertEqual(parsed[0]["net_total"], "102.00")

    def test_parity_with_summary_export(self):
        self._sale(
            self.salon,
            [("service", "85.00", 1, "10.00"),
             ("series", "100.00", 1)],
            sale_discount="5.00")
        last = self.day + datetime.timedelta(days=1)
        self.assertEqual(
            export_daily_sales(self.salon, self.day, last),
            export_summary(self.salon, self.day, last))
        self.assertEqual(
            export_daily_sales_csv(self.salon, self.day, last),
            export_summary_csv(self.salon, self.day, last))

    def test_read_only_records_unchanged(self):
        self._sale(self.salon, [("service", "85.00", 1)])
        before = (Sale.objects.count(), SaleItem.objects.count())
        export_daily_sales(self.salon, self.day)
        export_daily_sales_csv(self.salon, self.day)
        self.assertEqual((Sale.objects.count(), SaleItem.objects.count()),
                         before)
