"""Tests for the insights export_staff_revenue --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_staff_revenue_csv``
service), that JSON parses to the dict rows from the new twins
``export_staff_revenue`` / ``export_staff_revenue_rows``
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

from bookings.models import Appointment
from checkout.models import Sale, SaleItem
from clients.models import Client
from insights.staff_revenue_export import (
    STAFF_REVENUE_FIELDNAMES,
    export_staff_revenue,
    export_staff_revenue_csv,
    export_staff_revenue_rows,
    staff_revenue_rows,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)


def _expected_json(salon, start=START, end=END):
    return json.dumps(export_staff_revenue(salon, start, end),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportStaffRevenueFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.staff_a = StaffMember.objects.create(
            salon=self.salon, display_name="Alice")
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Olga")
        self.client_a = Client.objects.create(
            salon=self.salon, first_name="Ann", last_name="A")
        self.client_b = Client.objects.create(
            salon=self.salon, first_name="Ben", last_name="B")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.cut = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        # Alice: attributed sale on Nov 3.
        start = datetime.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        Appointment.objects.create(
            client=self.client_a, staff_member=self.staff_a,
            service=self.cut, start=start,
            end=start + timedelta(minutes=45))
        sale = Sale.objects.create(
            salon=self.salon, client=self.client_a,
            status=Sale.Status.COMPLETED)
        stamp = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, service=self.cut,
            quantity=1, unit_price=Decimal("85.00"))
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.PRODUCT,
            quantity=1, unit_price=Decimal("24.00"))
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERIES,
            quantity=1, unit_price=Decimal("150.00"))
        # Unattributed: sale with no appointment on Nov 5.
        sale2 = Sale.objects.create(
            salon=self.salon, client=self.client_b,
            status=Sale.Status.COMPLETED)
        stamp2 = datetime.datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale2.pk).update(
            created_at=stamp2, completed_at=stamp2)
        SaleItem.objects.create(
            sale=sale2, kind=SaleItem.Kind.SERVICE, service=self.cut,
            quantity=1, unit_price=Decimal("30.00"))

    def _pinned_csv(self):
        return (
            ",".join(STAFF_REVENUE_FIELDNAMES) + "\n"
            "Alice,85.00,24.00,150.00,259.00\n"
            "Unattributed,30.00,0.00,0.00,30.00\n"
        )

    def _pinned_rows(self):
        return [
            {"staff_name": "Alice", "service_revenue": "85.00",
             "retail_revenue": "24.00", "series_revenue": "150.00",
             "total": "259.00"},
            {"staff_name": "Unattributed", "service_revenue": "30.00",
             "retail_revenue": "0.00", "series_revenue": "0.00",
             "total": "30.00"},
        ]

    def _call(self, **kwargs):
        out = io.StringIO()
        call_command("export_staff_revenue", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_staff_revenue_csv(self.salon, START, END),
            self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(
            self._call(),
            export_staff_revenue_csv(self.salon, START, END))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_staff_revenue", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_staff_revenue(self.salon, START, END)
        self.assertEqual(rows, self._pinned_rows())
        self.assertEqual(
            export_staff_revenue_rows(self.salon, START, END), rows)
        self.assertEqual(staff_revenue_rows(self.salon, START, END), rows)
        parsed = list(csv.DictReader(io.StringIO(
            export_staff_revenue_csv(self.salon, START, END))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in rows], parsed)
        self.assertEqual([list(row) for row in rows],
                         [STAFF_REVENUE_FIELDNAMES] * len(rows))

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_staff_revenue(self.salon, START, END)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon))

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_staff_revenue_csv(self.salon, START, END))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_staff_revenue", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon))

    def test_json_output_file(self):
        out = io.StringIO()
        mocked = mock.mock_open()
        with mock.patch(
                "insights.management.commands.export_staff_revenue"
                ".open", mocked, create=True):
            call_command("export_staff_revenue", salon_id=self.salon.pk,
                         start_date=START, end_date=END, format="json",
                         output="staff_revenue.json", stdout=out)
        mocked.assert_called_once_with(
            "staff_revenue.json", "w", encoding="utf-8", newline="")
        handle = mocked()
        handle.write.assert_called_once_with(_expected_json(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        mocked = mock.mock_open()
        with mock.patch(
                "insights.management.commands.export_staff_revenue"
                ".open", mocked, create=True):
            call_command("export_staff_revenue", salon_id=self.salon.pk,
                         start_date=START, end_date=END,
                         output="staff_revenue.csv", stdout=out)
        mocked.assert_called_once_with(
            "staff_revenue.csv", "w", encoding="utf-8", newline="")
        handle = mocked()
        handle.write.assert_called_once_with(self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_window_json_and_csv_agree(self):
        start = START + timedelta(days=30)
        end = END + timedelta(days=30)
        self.assertEqual(export_staff_revenue(self.salon, start, end), [])
        self.assertEqual(
            export_staff_revenue_csv(self.salon, start, end),
            ",".join(STAFF_REVENUE_FIELDNAMES) + "\n")
        out = io.StringIO()
        call_command("export_staff_revenue", salon_id=self.salon.pk,
                     start_date=start, end_date=end, format="json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(out.getvalue(), "[]\n")

    def test_salon_scoping_other_salon_data_does_not_leak(self):
        other_client = Client.objects.create(
            salon=self.other, first_name="Ora", last_name="O")
        start = datetime.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        Appointment.objects.create(
            client=other_client, staff_member=self.other_staff,
            service=self.cut, start=start,
            end=start + timedelta(minutes=45))
        sale = Sale.objects.create(
            salon=self.other, client=other_client,
            status=Sale.Status.COMPLETED)
        stamp = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, service=self.cut,
            quantity=1, unit_price=Decimal("70.00"))
        self.assertEqual(
            export_staff_revenue(self.salon, START, END),
            self._pinned_rows())
        other_rows = export_staff_revenue(self.other, START, END)
        self.assertEqual(len(other_rows), 1)
        self.assertEqual(other_rows[0]["staff_name"], "Olga")
        self.assertEqual(other_rows[0]["total"], "70.00")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_staff_revenue", "--salon-id",
                         str(self.salon.pk), "--start-date",
                         START.isoformat(), "--end-date", END.isoformat(),
                         "--format", "xml", stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_staff_revenue", salon_id=999999,
                         start_date=START, end_date=END, format="json",
                         stdout=io.StringIO())

    def test_missing_dates_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_staff_revenue", salon_id=self.salon.pk,
                         format="json", stdout=io.StringIO())

    def test_bad_date_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_staff_revenue", salon_id=self.salon.pk,
                         start_date="bad", end_date=END, format="json",
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        mocked = mock.mock_open()
        mocked.side_effect = OSError("cannot write")
        with mock.patch(
                "insights.management.commands.export_staff_revenue"
                ".open", mocked, create=True):
            with self.assertRaises(CommandError):
                call_command("export_staff_revenue",
                             salon_id=self.salon.pk, start_date=START,
                             end_date=END, format="json",
                             output="out.json", stdout=io.StringIO())
