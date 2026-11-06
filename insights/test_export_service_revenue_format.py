"""Tests for the insights export_service_revenue --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_service_revenue_csv``
service), that JSON parses to the dict rows from the new twins
``export_service_revenue`` / ``export_service_revenue_rows``
-- the same rows the CSV is built from -- serialised with
``DjangoJSONEncoder`` (indent=2 + trailing newline), and that
unknown formats fail cleanly.
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
from insights.service_revenue_export import (
    SERVICE_REVENUE_FIELDNAMES,
    export_service_revenue,
    export_service_revenue_csv,
    export_service_revenue_rows,
    service_revenue_rows,
)
from saloncore.models import Salon, Service, ServiceCategory

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)


def _expected_json(salon, start=START, end=END):
    return json.dumps(export_service_revenue(salon, start, end),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportServiceRevenueFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.cut = Service.objects.create(
            category=cat, name="Haircut", service_minutes=60)
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED)
        stamp = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, service=self.cut,
            quantity=1, unit_price=Decimal("90.00"))
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, description="Mystery",
            quantity=1, unit_price=Decimal("30.00"))

    def _pinned_csv(self):
        return (
            ",".join(SERVICE_REVENUE_FIELDNAMES) + "\n"
            f"{self.cut.pk},Haircut,90.00,1,1,1,60,60,90.00\n"
            ",Mystery,30.00,1,1,1,,,\n"
        )

    def _pinned_rows(self):
        return [
            {"service_id": self.cut.pk, "service_name": "Haircut",
             "revenue": "90.00", "quantity": 1, "line_count": 1,
             "sale_count": 1, "duration_minutes": 60,
             "total_duration_minutes": 60, "revenue_per_hour": "90.00"},
            {"service_id": "", "service_name": "Mystery",
             "revenue": "30.00", "quantity": 1, "line_count": 1,
             "sale_count": 1, "duration_minutes": "",
             "total_duration_minutes": "", "revenue_per_hour": ""},
        ]

    def _call(self, **kwargs):
        out = io.StringIO()
        call_command("export_service_revenue", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_service_revenue_csv(self.salon, START, END),
            self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(
            self._call(),
            export_service_revenue_csv(self.salon, START, END))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_service_revenue", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_service_revenue(self.salon, START, END)
        self.assertEqual(rows, self._pinned_rows())
        self.assertEqual(
            export_service_revenue_rows(self.salon, START, END), rows)
        self.assertEqual(service_revenue_rows(self.salon, START, END), rows)
        parsed = list(csv.DictReader(io.StringIO(
            export_service_revenue_csv(self.salon, START, END))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in rows], parsed)
        self.assertEqual([list(row) for row in rows],
                         [SERVICE_REVENUE_FIELDNAMES] * len(rows))

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_service_revenue(self.salon, START, END)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon))

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_service_revenue_csv(self.salon, START, END))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_service_revenue", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon))

    # File output is verified through a mocked open, as in
    # test_service_revenue: real filesystem writes are blocked
    # in some test environments.
    def test_json_output_file(self):
        out = io.StringIO()
        mocked = mock.mock_open()
        with mock.patch(
                "insights.management.commands.export_service_revenue"
                ".open", mocked, create=True):
            call_command("export_service_revenue", salon_id=self.salon.pk,
                         start_date=START, end_date=END, format="json",
                         output="service_revenue.json", stdout=out)
        mocked.assert_called_once_with(
            "service_revenue.json", "w", encoding="utf-8", newline="")
        handle = mocked()
        handle.write.assert_called_once_with(_expected_json(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        mocked = mock.mock_open()
        with mock.patch(
                "insights.management.commands.export_service_revenue"
                ".open", mocked, create=True):
            call_command("export_service_revenue", salon_id=self.salon.pk,
                         start_date=START, end_date=END,
                         output="service_revenue.csv", stdout=out)
        mocked.assert_called_once_with(
            "service_revenue.csv", "w", encoding="utf-8", newline="")
        handle = mocked()
        handle.write.assert_called_once_with(self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_window_json_and_csv_agree(self):
        start = START + timedelta(days=30)
        end = END + timedelta(days=30)
        self.assertEqual(export_service_revenue(self.salon, start, end), [])
        self.assertEqual(
            export_service_revenue_csv(self.salon, start, end),
            ",".join(SERVICE_REVENUE_FIELDNAMES) + "\n")
        out = io.StringIO()
        call_command("export_service_revenue", salon_id=self.salon.pk,
                     start_date=start, end_date=end, format="json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(out.getvalue(), "[]\n")

    def test_salon_scoping_other_salon_data_does_not_leak(self):
        other_cat = ServiceCategory.objects.create(
            salon=self.other, name="Hair")
        other_cut = Service.objects.create(
            category=other_cat, name="Haircut", service_minutes=60)
        sale = Sale.objects.create(
            salon=self.other, status=Sale.Status.COMPLETED)
        stamp = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, service=other_cut,
            quantity=1, unit_price=Decimal("999.00"))
        self.assertEqual(
            export_service_revenue(self.salon, START, END),
            self._pinned_rows())
        other_rows = export_service_revenue(self.other, START, END)
        self.assertEqual(len(other_rows), 1)
        self.assertEqual(other_rows[0]["revenue"], "999.00")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_service_revenue", "--salon-id",
                         str(self.salon.pk), "--start-date",
                         START.isoformat(), "--end-date", END.isoformat(),
                         "--format", "xml", stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_service_revenue", salon_id=999999,
                         start_date=START, end_date=END, format="json",
                         stdout=io.StringIO())

    def test_missing_dates_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_service_revenue", salon_id=self.salon.pk,
                         format="json", stdout=io.StringIO())

    def test_bad_date_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_service_revenue", salon_id=self.salon.pk,
                         start_date="bad", end_date=END, format="json",
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        mocked = mock.mock_open()
        mocked.side_effect = OSError("cannot write")
        with mock.patch(
                "insights.management.commands.export_service_revenue"
                ".open", mocked, create=True):
            with self.assertRaises(CommandError):
                call_command("export_service_revenue",
                             salon_id=self.salon.pk, start_date=START,
                             end_date=END, format="json",
                             output="out.json", stdout=io.StringIO())
