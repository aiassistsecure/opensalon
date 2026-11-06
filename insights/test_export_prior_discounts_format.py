"""Tests for the insights export_prior_discounts command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_prior_discounts_csv``
service), that JSON parses to the dict rows from the new twin
``export_prior_discounts`` -- the same rows the CSV is built
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
from insights.prior_discounts_export import (
    PRIOR_DISCOUNTS_FIELDNAMES,
    export_prior_discounts,
    export_prior_discounts_csv,
)
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)
PRIOR_START = START - timedelta(days=7)
PRIOR_END = START - timedelta(days=1)


def _expected_json(salon, start=START, end=END):
    return json.dumps(export_prior_discounts(salon, start, end),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportPriorDiscountsFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self._sale(date(2026, 10, 28), "100.00",
                   sale_discount="5.00", item_discount="15.00")
        self._sale(date(2026, 11, 5), "200.00",
                   sale_discount="10.00", item_discount="20.00")

    def _sale(self, day, price, sale_discount="0.00",
              item_discount="0.00", salon=None):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED,
            discount_amount=Decimal(sale_discount))
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal(price),
            discount_amount=Decimal(item_discount))
        return sale

    def _pinned_csv(self):
        dates = (f"{START.isoformat()},{END.isoformat()},"
                 f"{PRIOR_START.isoformat()},{PRIOR_END.isoformat()}")
        return (
            ",".join(PRIOR_DISCOUNTS_FIELDNAMES) + "\n"
            f"discount_total,{dates},30.00,20.00,10.00,50.00\n"
            f"gross,{dates},200.00,100.00,100.00,100.00\n"
            f"discount_share_percent,{dates},15.00,20.00,-5.00,-25.00\n"
        )

    def _pinned_rows(self):
        dates = {
            "current_start_date": START.isoformat(),
            "current_end_date": END.isoformat(),
            "prior_start_date": PRIOR_START.isoformat(),
            "prior_end_date": PRIOR_END.isoformat(),
        }
        return [
            {"metric": "discount_total", **dates, "current": "30.00",
             "prior": "20.00", "delta": "10.00", "percent_change": "50.00"},
            {"metric": "gross", **dates, "current": "200.00",
             "prior": "100.00", "delta": "100.00",
             "percent_change": "100.00"},
            {"metric": "discount_share_percent", **dates,
             "current": "15.00", "prior": "20.00", "delta": "-5.00",
             "percent_change": "-25.00"},
        ]

    def _call(self, **kwargs):
        out = io.StringIO()
        call_command("export_prior_discounts", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_prior_discounts_csv(self.salon, START, END),
            self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(
            self._call(),
            export_prior_discounts_csv(self.salon, START, END))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_prior_discounts", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_prior_discounts(self.salon, START, END)
        self.assertEqual(rows, self._pinned_rows())
        parsed = list(csv.DictReader(io.StringIO(
            export_prior_discounts_csv(self.salon, START, END))))
        self.assertEqual(rows, parsed)
        self.assertEqual([list(row) for row in rows],
                         [PRIOR_DISCOUNTS_FIELDNAMES] * len(rows))

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_prior_discounts(self.salon, START, END)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon))

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_prior_discounts_csv(self.salon, START, END))))
        self.assertEqual(json_rows, csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_prior_discounts", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon))

    def test_json_output_file(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_discounts.json")
            call_command("export_prior_discounts",
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
            path = os.path.join(tmp, "prior_discounts.csv")
            call_command("export_prior_discounts",
                         salon_id=self.salon.pk, start_date=START,
                         end_date=END, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_salon_json_and_csv_agree(self):
        rows = export_prior_discounts(self.other, START, END)
        self.assertEqual([r["metric"] for r in rows],
                         ["discount_total", "gross",
                          "discount_share_percent"])
        share = rows[2]
        self.assertEqual(
            (share["current"], share["prior"], share["delta"],
             share["percent_change"]), ("", "", "", ""))
        out = io.StringIO()
        call_command("export_prior_discounts", salon_id=self.other.pk,
                     start_date=START, end_date=END, format="json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(out.getvalue(), _expected_json(self.other))

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_prior_discounts", "--salon-id",
                         str(self.salon.pk), "--start-date",
                         START.isoformat(), "--end-date", END.isoformat(),
                         "--format", "xml", stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_discounts", salon_id=999999,
                         start_date=START, end_date=END, format="json",
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.json")
            with self.assertRaises(CommandError):
                call_command("export_prior_discounts",
                             salon_id=self.salon.pk, start_date=START,
                             end_date=END, format="json", output=path,
                             stdout=io.StringIO())
