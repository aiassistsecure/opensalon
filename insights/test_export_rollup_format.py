"""Tests for the insights export_rollup --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_rollup_csv``
service), that JSON parses to the dict rows from the new twins
``export_rollup`` / ``export_weekly_rollup`` /
``export_monthly_rollup`` -- the same rows the CSV is built
from -- serialised with ``DjangoJSONEncoder`` (indent=2 +
trailing newline), and that unknown formats fail cleanly.
"""
import csv
import io
import json
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.rollup_export import (
    ROLLUP_FIELDNAMES,
    export_monthly_rollup,
    export_monthly_rollup_csv,
    export_rollup,
    export_rollup_csv,
    export_weekly_rollup,
    export_weekly_rollup_csv,
)
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
END = date(2026, 11, 8)  # Sunday; ISO week Mon 2026-11-02..Sun 11-08


def _expected_json(salon, **kwargs):
    kwargs.setdefault("days", 14)
    kwargs.setdefault("end_date", END)
    return json.dumps(export_rollup(salon, **kwargs),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportRollupFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self._sale_on(date(2026, 10, 26), SaleItem.Kind.SERVICE, "100.00")
        self._sale_on(date(2026, 10, 28), SaleItem.Kind.PRODUCT, "20.00")
        self._sale_on(date(2026, 11, 1), SaleItem.Kind.SERIES, "50.00")
        self._sale_on(date(2026, 11, 2), SaleItem.Kind.SERVICE, "85.00")
        self._sale_on(date(2026, 11, 8), SaleItem.Kind.PRODUCT, "24.00",
                      quantity=2)
        self._sale_on(date(2026, 11, 8), SaleItem.Kind.SERIES, "30.00")

    def _sale_on(self, day, kind, price, salon=None, quantity=1):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED)
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(sale=sale, kind=kind, quantity=quantity,
                                unit_price=Decimal(price))
        return sale

    def _pinned_csv(self):
        return (
            ",".join(ROLLUP_FIELDNAMES) + "\n"
            "week,2026-W44,2026-10-26,2026-11-01,7,"
            "100.00,20.00,50.00,170.00\n"
            "week,2026-W45,2026-11-02,2026-11-08,7,"
            "85.00,48.00,30.00,163.00\n"
        )

    def _pinned_rows(self):
        return [
            {"granularity": "week", "label": "2026-W44",
             "period_start": "2026-10-26", "period_end": "2026-11-01",
             "day_count": "7", "service": "100.00", "retail": "20.00",
             "series": "50.00", "total": "170.00"},
            {"granularity": "week", "label": "2026-W45",
             "period_start": "2026-11-02", "period_end": "2026-11-08",
             "day_count": "7", "service": "85.00", "retail": "48.00",
             "series": "30.00", "total": "163.00"},
        ]

    def _pinned_monthly_rows(self):
        return [
            {"granularity": "month", "label": "2026-10",
             "period_start": "2026-10-26", "period_end": "2026-10-31",
             "day_count": "6", "service": "100.00", "retail": "20.00",
             "series": "0.00", "total": "120.00"},
            {"granularity": "month", "label": "2026-11",
             "period_start": "2026-11-01", "period_end": "2026-11-08",
             "day_count": "8", "service": "85.00", "retail": "48.00",
             "series": "80.00", "total": "213.00"},
        ]

    def _call(self, **kwargs):
        out = io.StringIO()
        call_command("export_rollup", salon_id=self.salon.pk, days=14,
                     end_date=END, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_rollup_csv(self.salon, days=14, end_date=END),
            self._pinned_csv())
        self.assertEqual(
            export_weekly_rollup_csv(self.salon, days=14, end_date=END),
            self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(
            self._call(),
            export_rollup_csv(self.salon, days=14, end_date=END))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_rollup", "--salon-id", str(self.salon.pk),
                     "--days", "14", "--end-date", END.isoformat(),
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_rollup(self.salon, days=14, end_date=END)
        self.assertEqual(rows, self._pinned_rows())
        parsed = list(csv.DictReader(io.StringIO(
            export_rollup_csv(self.salon, days=14, end_date=END))))
        self.assertEqual(rows, parsed)
        self.assertEqual([list(row) for row in rows],
                         [ROLLUP_FIELDNAMES] * len(rows))

    def test_weekly_and_monthly_twins_mirror_csv_variants(self):
        self.assertEqual(
            export_weekly_rollup(self.salon, days=14, end_date=END),
            self._pinned_rows())
        monthly = export_monthly_rollup(
            self.salon, days=14, end_date=END)
        self.assertEqual(monthly, self._pinned_monthly_rows())
        parsed = list(csv.DictReader(io.StringIO(
            export_monthly_rollup_csv(self.salon, days=14,
                                      end_date=END))))
        self.assertEqual(monthly, parsed)
        self.assertEqual(
            export_rollup(self.salon, granularity="month", days=14,
                          end_date=END), monthly)

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_rollup(self.salon, days=14, end_date=END)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon))

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_rollup_csv(self.salon, days=14, end_date=END))))
        self.assertEqual(json_rows, csv_rows)

    def test_json_monthly_via_command(self):
        out = io.StringIO()
        call_command("export_rollup", salon_id=self.salon.pk,
                     granularity="month", days=14, end_date=END,
                     format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         self._pinned_monthly_rows())
        self.assertEqual(out.getvalue(), _expected_json(
            self.salon, granularity="month"))

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_rollup", "--salon-id", str(self.salon.pk),
                     "--days", "14", "--end-date", END.isoformat(),
                     "--format", "json", stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon))

    def test_json_output_file(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rollup.json")
            call_command("export_rollup", salon_id=self.salon.pk,
                         days=14, end_date=END, format="json",
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, _expected_json(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rollup.csv")
            call_command("export_rollup", salon_id=self.salon.pk,
                         days=14, end_date=END, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_window_json_and_csv_agree(self):
        self.assertEqual(
            export_rollup(self.salon, days=0, end_date=END), [])
        self.assertEqual(
            export_rollup_csv(self.salon, days=0, end_date=END),
            ",".join(ROLLUP_FIELDNAMES) + "\n")
        out = io.StringIO()
        call_command("export_rollup", salon_id=self.salon.pk, days=0,
                     end_date=END, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(out.getvalue(), "[]\n")

    def test_salon_scoping_other_salon_data_does_not_leak(self):
        self._sale_on(END, SaleItem.Kind.SERVICE, "999.00",
                      salon=self.other)
        self.assertEqual(
            export_rollup(self.salon, days=14, end_date=END),
            self._pinned_rows())
        other_rows = export_rollup(self.other, days=14, end_date=END)
        self.assertEqual(other_rows[-1]["total"], "999.00")
        self.assertEqual(other_rows[0]["total"], "0.00")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_rollup", "--salon-id",
                         str(self.salon.pk), "--format", "xml",
                         stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_rollup", salon_id=999999, days=14,
                         end_date=END, format="json",
                         stdout=io.StringIO())

    def test_bad_granularity_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_rollup", salon_id=self.salon.pk,
                         granularity="quarter", days=14, end_date=END,
                         format="json", stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.json")
            with self.assertRaises(CommandError):
                call_command("export_rollup", salon_id=self.salon.pk,
                             days=14, end_date=END, format="json",
                             output=path, stdout=io.StringIO())
