"""Tests for the insights export_prior_period command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_prior_period_csv``
service), that JSON parses to the dict rows from the new twin
``export_prior_period`` -- the same rows the CSV is built
from -- serialised with ``DjangoJSONEncoder`` (indent=2 +
trailing newline), and that unknown formats fail cleanly.
"""
import csv
import io
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.prior_period_export import (
    PRIOR_PERIOD_FIELDNAMES,
    export_prior_period,
    export_prior_period_csv,
)
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)
PRIOR_START = START - timedelta(days=7)
PRIOR_END = START - timedelta(days=1)


def _expected_json(salon, start=START, end=END):
    return json.dumps(export_prior_period(salon, start, end),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportPriorPeriodFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        cur = self._sale(date(2026, 11, 5))
        self._item(cur, SaleItem.Kind.SERVICE, "100.00")
        self._item(cur, SaleItem.Kind.PRODUCT, "50.00")
        self._item(cur, SaleItem.Kind.SERIES, "200.00")
        prior = self._sale(date(2026, 10, 29))
        self._item(prior, SaleItem.Kind.SERVICE, "50.00")
        self._item(prior, SaleItem.Kind.PRODUCT, "50.00")
        self._item(prior, SaleItem.Kind.SERIES, "100.00")

    def _sale(self, day, salon=None):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED)
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        return sale

    def _item(self, sale, kind, price, quantity=1):
        return SaleItem.objects.create(
            sale=sale, kind=kind, quantity=quantity,
            unit_price=Decimal(price))

    def _pinned_csv(self):
        dates = (f"{START.isoformat()},{END.isoformat()},"
                 f"{PRIOR_START.isoformat()},{PRIOR_END.isoformat()}")
        return (
            ",".join(PRIOR_PERIOD_FIELDNAMES) + "\n"
            f"service,{dates},100.00,50.00,50.00,100.00\n"
            f"retail,{dates},50.00,50.00,0.00,0.00\n"
            f"series,{dates},200.00,100.00,100.00,100.00\n"
            f"total,{dates},350.00,200.00,150.00,75.00\n"
        )

    def _pinned_rows(self):
        dates = {
            "current_start_date": START.isoformat(),
            "current_end_date": END.isoformat(),
            "prior_start_date": PRIOR_START.isoformat(),
            "prior_end_date": PRIOR_END.isoformat(),
        }
        return [
            {"component": "service", **dates, "current": "100.00",
             "prior": "50.00", "delta": "50.00",
             "percent_change": "100.00"},
            {"component": "retail", **dates, "current": "50.00",
             "prior": "50.00", "delta": "0.00", "percent_change": "0.00"},
            {"component": "series", **dates, "current": "200.00",
             "prior": "100.00", "delta": "100.00",
             "percent_change": "100.00"},
            {"component": "total", **dates, "current": "350.00",
             "prior": "200.00", "delta": "150.00",
             "percent_change": "75.00"},
        ]

    def _call(self, **kwargs):
        out = io.StringIO()
        call_command("export_prior_period", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_prior_period_csv(self.salon, START, END),
            self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(
            self._call(),
            export_prior_period_csv(self.salon, START, END))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_prior_period", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_prior_period(self.salon, START, END)
        self.assertEqual(rows, self._pinned_rows())
        parsed = list(csv.DictReader(io.StringIO(
            export_prior_period_csv(self.salon, START, END))))
        self.assertEqual(rows, parsed)
        self.assertEqual([list(row) for row in rows],
                         [PRIOR_PERIOD_FIELDNAMES] * len(rows))

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_prior_period(self.salon, START, END)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon))

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_prior_period_csv(self.salon, START, END))))
        self.assertEqual(json_rows, csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_prior_period", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon))

    def test_json_output_file(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_period.json")
            call_command("export_prior_period",
                         salon_id=self.salon.pk, start_date=START,
                         end_date=END, format="json", output=path,
                         stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, _expected_json(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_period.csv")
            call_command("export_prior_period",
                         salon_id=self.salon.pk, start_date=START,
                         end_date=END, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_salon_json_and_csv_agree(self):
        rows = export_prior_period(self.other, START, END)
        self.assertEqual([r["component"] for r in rows],
                         ["service", "retail", "series", "total"])
        for row in rows:
            self.assertEqual(
                (row["current"], row["prior"], row["delta"],
                 row["percent_change"]), ("0.00", "0.00", "0.00", ""))
        out = io.StringIO()
        call_command("export_prior_period", salon_id=self.other.pk,
                     start_date=START, end_date=END, format="json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(out.getvalue(), _expected_json(self.other))

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_prior_period", "--salon-id",
                         str(self.salon.pk), "--start-date",
                         START.isoformat(), "--end-date", END.isoformat(),
                         "--format", "xml", stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_period", salon_id=999999,
                         start_date=START, end_date=END, format="json",
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.json")
            with self.assertRaises(CommandError):
                call_command("export_prior_period",
                             salon_id=self.salon.pk, start_date=START,
                             end_date=END, format="json", output=path,
                             stdout=io.StringIO())
