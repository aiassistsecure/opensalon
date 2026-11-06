"""Tests for the insights export_category_mix command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_category_mix_csv``
service), that JSON parses to the dict rows from the new twin
``export_category_mix`` -- the same rows the CSV is built
from -- serialised with ``DjangoJSONEncoder`` (indent=2 +
trailing newline), and that unknown formats fail cleanly.
"""
import csv
import datetime
import io
import json
import os
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.category_mix_export import (
    CATEGORY_MIX_FIELDNAMES,
    export_category_mix,
    export_category_mix_csv,
)
from saloncore.models import Salon, Service, ServiceCategory

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)


def _expected_json(salon, start=START, end=END):
    return json.dumps(export_category_mix(salon, start, end), indent=2,
                      cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportCategoryMixFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.cat = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        cut = Service.objects.create(
            category=self.cat, name="Cut", service_minutes=45)
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED)
        stamp = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal("80.00"), service=cut)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal("20.00"), description="Mystery")

    def _pinned_csv(self):
        return (
            ",".join(CATEGORY_MIX_FIELDNAMES) + "\n"
            f"{self.cat.pk},Hair,80.00,1,1,1,1,80.00,50.00\n"
            ",Uncategorized,20.00,1,1,1,0,20.00,50.00\n"
        )

    def _pinned_rows(self):
        return [
            {"category_id": self.cat.pk, "category_name": "Hair",
             "revenue": "80.00", "quantity": 1, "line_count": 1,
             "sale_count": 1, "service_count": 1,
             "revenue_share_percent": "80.00",
             "quantity_share_percent": "50.00"},
            {"category_id": "", "category_name": "Uncategorized",
             "revenue": "20.00", "quantity": 1, "line_count": 1,
             "sale_count": 1, "service_count": 0,
             "revenue_share_percent": "20.00",
             "quantity_share_percent": "50.00"},
        ]

    def _call(self, **kwargs):
        out = io.StringIO()
        call_command("export_category_mix", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(export_category_mix_csv(self.salon, START, END),
                         self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(self._call(),
                         export_category_mix_csv(self.salon, START, END))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_category_mix", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_category_mix(self.salon, START, END)
        self.assertEqual(rows, self._pinned_rows())
        parsed = list(csv.DictReader(io.StringIO(
            export_category_mix_csv(self.salon, START, END))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in rows],
            parsed)
        self.assertEqual([list(row) for row in rows],
                         [CATEGORY_MIX_FIELDNAMES] * len(rows))

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_category_mix(self.salon, START, END)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon))
        self.assertIn("Hair", text)
        self.assertIn("Uncategorized", text)

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_category_mix_csv(self.salon, START, END))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_category_mix", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon))

    def test_json_output_file(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "category_mix.json")
            call_command("export_category_mix", salon_id=self.salon.pk,
                         start_date=START, end_date=END, format="json",
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, _expected_json(self.salon))
        self.assertEqual(json.loads(text),
                         _parsed(export_category_mix(self.salon, START, END)))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "category_mix.csv")
            call_command("export_category_mix", salon_id=self.salon.pk,
                         start_date=START, end_date=END,
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_window_json_and_csv(self):
        start = START + timedelta(days=30)
        end = END + timedelta(days=30)
        out = io.StringIO()
        call_command("export_category_mix", salon_id=self.salon.pk,
                     start_date=start, end_date=end, format="json",
                     stdout=out)
        self.assertEqual(out.getvalue(), "[]\n")
        self.assertEqual(export_category_mix(self.salon, start, end), [])
        out = io.StringIO()
        call_command("export_category_mix", salon_id=self.salon.pk,
                     start_date=start, end_date=end, stdout=out)
        self.assertEqual(out.getvalue(),
                         ",".join(CATEGORY_MIX_FIELDNAMES) + "\n")

    def test_json_scopes_to_salon(self):
        out = io.StringIO()
        call_command("export_category_mix", salon_id=self.other.pk,
                     start_date=START, end_date=END, format="json",
                     stdout=out)
        self.assertEqual(out.getvalue(), "[]\n")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_category_mix", "--salon-id",
                         str(self.salon.pk), "--start-date",
                         START.isoformat(), "--end-date", END.isoformat(),
                         "--format", "xml", stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_category_mix", salon_id=999999,
                         start_date=START, end_date=END, format="json",
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.json")
            with self.assertRaises(CommandError):
                call_command("export_category_mix",
                             salon_id=self.salon.pk, start_date=START,
                             end_date=END, format="json", output=path,
                             stdout=io.StringIO())
