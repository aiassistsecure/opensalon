"""Tests for the insights export_trend --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_trend_csv``
service), that JSON parses to the dict rows from the new twins
``export_trend`` / ``export_trend_rows`` -- the same rows the
CSV is built from -- serialised with ``DjangoJSONEncoder``
(indent=2 + trailing newline), and that unknown formats fail
cleanly.
"""
import csv
import datetime
import io
import json
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.trend_export import (
    TREND_FIELDNAMES,
    export_trend,
    export_trend_csv,
    export_trend_rows,
    trend_rows,
)
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
END = date(2026, 11, 8)


def _expected_json(salon, days=3, end_date=END):
    return json.dumps(export_trend(salon, days=days, end_date=end_date),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportTrendFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        today_sale = self._sale(day_offset=0)
        self._item(today_sale, SaleItem.Kind.SERVICE, "85.00")
        self._item(today_sale, SaleItem.Kind.PRODUCT, "24.00", quantity=2)
        self._item(today_sale, SaleItem.Kind.SERIES, "150.00")
        yesterday = self._sale(day_offset=1)
        self._item(yesterday, SaleItem.Kind.SERVICE, "50.00")

    def _sale(self, *, day_offset=0, salon=None):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED)
        stamp = datetime.datetime(2026, 11, 8, 12, 0, tzinfo=UTC) \
            - timedelta(days=day_offset)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        return sale

    def _item(self, sale, kind, price, quantity=1):
        return SaleItem.objects.create(
            sale=sale, kind=kind, quantity=quantity,
            unit_price=Decimal(price))

    def _pinned_csv(self):
        return (
            ",".join(TREND_FIELDNAMES) + "\n"
            "2026-11-06,0.00,0.00,0.00,0.00,0.00\n"
            "2026-11-07,50.00,0.00,0.00,50.00,25.00\n"
            "2026-11-08,85.00,48.00,150.00,283.00,111.00\n"
        )

    def _pinned_rows(self):
        return [
            {"date": "2026-11-06", "service": "0.00", "retail": "0.00",
             "series": "0.00", "total": "0.00",
             "moving_average_7d": "0.00"},
            {"date": "2026-11-07", "service": "50.00", "retail": "0.00",
             "series": "0.00", "total": "50.00",
             "moving_average_7d": "25.00"},
            {"date": "2026-11-08", "service": "85.00", "retail": "48.00",
             "series": "150.00", "total": "283.00",
             "moving_average_7d": "111.00"},
        ]

    def _call(self, **kwargs):
        out = io.StringIO()
        call_command("export_trend", salon_id=self.salon.pk,
                     days=3, end_date=END, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_trend_csv(self.salon, days=3, end_date=END),
            self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(
            self._call(),
            export_trend_csv(self.salon, days=3, end_date=END))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_trend", "--salon-id", str(self.salon.pk),
                     "--days", "3", "--end-date", END.isoformat(),
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_trend(self.salon, days=3, end_date=END)
        self.assertEqual(rows, self._pinned_rows())
        self.assertEqual(
            export_trend_rows(self.salon, days=3, end_date=END), rows)
        self.assertEqual(trend_rows(self.salon, days=3, end_date=END), rows)
        parsed = list(csv.DictReader(io.StringIO(
            export_trend_csv(self.salon, days=3, end_date=END))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in rows], parsed)
        self.assertEqual([list(row) for row in rows],
                         [TREND_FIELDNAMES] * len(rows))

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_trend(self.salon, days=3, end_date=END)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon))

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_trend_csv(self.salon, days=3, end_date=END))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_trend", "--salon-id", str(self.salon.pk),
                     "--days", "3", "--end-date", END.isoformat(),
                     "--format", "json", stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon))

    # File output is verified through a mocked open, as in
    # test_export_service_revenue_format: real filesystem
    # writes are blocked in some test environments.
    def test_json_output_file(self):
        out = io.StringIO()
        mocked = mock.mock_open()
        with mock.patch(
                "insights.management.commands.export_trend.open",
                mocked, create=True):
            call_command("export_trend", salon_id=self.salon.pk,
                         days=3, end_date=END, format="json",
                         output="trend.json", stdout=out)
        mocked.assert_called_once_with(
            "trend.json", "w", encoding="utf-8", newline="")
        handle = mocked()
        handle.write.assert_called_once_with(_expected_json(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        mocked = mock.mock_open()
        with mock.patch(
                "insights.management.commands.export_trend.open",
                mocked, create=True):
            call_command("export_trend", salon_id=self.salon.pk,
                         days=3, end_date=END,
                         output="trend.csv", stdout=out)
        mocked.assert_called_once_with(
            "trend.csv", "w", encoding="utf-8", newline="")
        handle = mocked()
        handle.write.assert_called_once_with(self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_window_json_and_csv_agree(self):
        self.assertEqual(export_trend(self.salon, days=0, end_date=END), [])
        self.assertEqual(
            export_trend_csv(self.salon, days=0, end_date=END),
            ",".join(TREND_FIELDNAMES) + "\n")
        out = io.StringIO()
        call_command("export_trend", salon_id=self.salon.pk,
                     days=0, end_date=END, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(out.getvalue(), "[]\n")

    def test_salon_scoping_other_salon_data_does_not_leak(self):
        other_sale = self._sale(salon=self.other)
        self._item(other_sale, SaleItem.Kind.SERVICE, "999.00")
        self.assertEqual(
            export_trend(self.salon, days=3, end_date=END),
            self._pinned_rows())
        other_rows = export_trend(self.other, days=3, end_date=END)
        self.assertEqual(other_rows[-1]["total"], "999.00")
        self.assertEqual(other_rows[-1]["service"], "999.00")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_trend", "--salon-id", str(self.salon.pk),
                         "--days", "3", "--end-date", END.isoformat(),
                         "--format", "xml", stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_trend", salon_id=999999,
                         days=3, end_date=END, format="json",
                         stdout=io.StringIO())

    def test_bad_date_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_trend", salon_id=self.salon.pk,
                         days=3, end_date="bad", format="json",
                         stdout=io.StringIO())

    def test_invalid_days_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_trend", salon_id=self.salon.pk,
                         days="not-a-number", end_date=END, format="json",
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        mocked = mock.mock_open()
        mocked.side_effect = OSError("cannot write")
        with mock.patch(
                "insights.management.commands.export_trend.open",
                mocked, create=True):
            with self.assertRaises(CommandError):
                call_command("export_trend", salon_id=self.salon.pk,
                             days=3, end_date=END, format="json",
                             output="out.json", stdout=io.StringIO())
