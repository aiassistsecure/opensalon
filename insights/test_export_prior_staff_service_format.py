"""Tests for the insights export_prior_staff_service --format.

Pins that CSV output (per --kind) is byte-identical to the
historical output, that JSON parses to the dict rows from the
new twins ``export_prior_staff`` / ``export_prior_service``
-- the same rows the CSVs are built from -- serialised with
``DjangoJSONEncoder`` (indent=2 + trailing newline), and that
unknown formats fail cleanly. --format applies per kind.
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

from bookings.models import Appointment
from checkout.models import Sale, SaleItem
from clients.models import Client
from insights.prior_staff_service import (
    PRIOR_SERVICE_FIELDNAMES,
    PRIOR_STAFF_FIELDNAMES,
    export_prior_service,
    export_prior_service_csv,
    export_prior_staff,
    export_prior_staff_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)
PRIOR_START = date(2026, 10, 26)
PRIOR_END = date(2026, 11, 1)


def _expected_json(rows):
    return json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportPriorStaffServiceFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.alice = StaffMember.objects.create(
            salon=self.salon, display_name="Alice")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Ann", last_name="A")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.cut = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        self._appt(date(2026, 11, 5))
        cur = self._sale(date(2026, 11, 5))
        self._item(cur, SaleItem.Kind.SERVICE, "100.00", self.cut)
        self._item(cur, SaleItem.Kind.PRODUCT, "50.00")
        self._appt(date(2026, 10, 29))
        pri = self._sale(date(2026, 10, 29))
        self._item(pri, SaleItem.Kind.SERVICE, "50.00", self.cut)

    def _appt(self, day):
        start = datetime(day.year, day.month, day.day, 10, 0, tzinfo=UTC)
        return Appointment.objects.create(
            client=self.client, staff_member=self.alice, service=self.cut,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)

    def _sale(self, day):
        sale = Sale.objects.create(
            salon=self.salon, client=self.client,
            status=Sale.Status.COMPLETED)
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        return sale

    def _item(self, sale, kind, price, service=None):
        return SaleItem.objects.create(
            sale=sale, kind=kind, quantity=1,
            unit_price=Decimal(price), service=service)

    def _pinned_staff_csv(self):
        return (
            ",".join(PRIOR_STAFF_FIELDNAMES) + "\n"
            f"Alice,{START},{END},{PRIOR_START},{PRIOR_END},"
            "150.00,50.00,100.00,200.00,1,1\n"
        )

    def _pinned_staff_rows(self):
        return [{
            "staff_name": "Alice",
            "current_start_date": START.isoformat(),
            "current_end_date": END.isoformat(),
            "prior_start_date": PRIOR_START.isoformat(),
            "prior_end_date": PRIOR_END.isoformat(),
            "current": "150.00", "prior": "50.00", "delta": "100.00",
            "percent_change": "200.00",
            "current_sale_count": 1, "prior_sale_count": 1,
        }]

    def _call(self, kind="staff", **kwargs):
        out = io.StringIO()
        call_command("export_prior_staff_service",
                     salon_id=self.salon.pk, kind=kind,
                     start_date=START, end_date=END, stdout=out, **kwargs)
        return out.getvalue()

    # -- CSV byte-identical, both kinds ---------------------------------
    def test_staff_csv_service_is_byte_identical_to_pinned(self):
        self.assertEqual(export_prior_staff_csv(self.salon, START, END),
                         self._pinned_staff_csv())

    def test_default_format_is_csv_byte_identical_both_kinds(self):
        self.assertEqual(self._call(kind="staff"),
                         self._pinned_staff_csv())
        self.assertEqual(self._call(kind="service"),
                         export_prior_service_csv(self.salon, START, END))

    def test_explicit_csv_matches_service_both_kinds(self):
        self.assertEqual(self._call(kind="staff", format="csv"),
                         self._pinned_staff_csv())
        self.assertEqual(self._call(kind="service", format="csv"),
                         export_prior_service_csv(self.salon, START, END))

    def test_explicit_csv_via_cli_flag(self):
        for kind, want in (
                ("staff", self._pinned_staff_csv()),
                ("service", export_prior_service_csv(
                    self.salon, START, END))):
            out = io.StringIO()
            call_command("export_prior_staff_service", "--salon-id",
                         str(self.salon.pk), "--kind", kind,
                         "--start-date", START.isoformat(),
                         "--end-date", END.isoformat(), "--format", "csv",
                         stdout=out)
            self.assertEqual(out.getvalue(), want)

    # -- Dict twins mirror CSV -------------------------------------------
    def test_dict_rows_mirror_csv_rows_both_kinds(self):
        for rows, csv_text, fields in (
                (export_prior_staff(self.salon, START, END),
                 export_prior_staff_csv(self.salon, START, END),
                 PRIOR_STAFF_FIELDNAMES),
                (export_prior_service(self.salon, START, END),
                 export_prior_service_csv(self.salon, START, END),
                 PRIOR_SERVICE_FIELDNAMES)):
            parsed = list(csv.DictReader(io.StringIO(csv_text)))
            self.assertEqual(
                parsed, [{k: str(v) for k, v in r.items()} for r in rows])
            self.assertEqual([list(r) for r in rows],
                             [fields] * len(rows))

    def test_staff_dict_rows_pinned(self):
        self.assertEqual(export_prior_staff(self.salon, START, END),
                         self._pinned_staff_rows())

    def test_service_dict_row_values(self):
        rows = export_prior_service(self.salon, START, END)
        self.assertEqual([r["service_name"] for r in rows], ["Haircut"])
        row = rows[0]
        self.assertEqual(
            (row["current"], row["prior"], row["delta"],
             row["percent_change"]), ("100.00", "50.00", "50.00", "100.00"))
        self.assertEqual(
            (row["current_quantity"], row["prior_quantity"],
             row["current_sale_count"], row["prior_sale_count"],
             row["current_line_count"], row["prior_line_count"]),
            (1, 1, 1, 1, 1, 1))
        self.assertEqual(
            (row["current_total_duration_minutes"],
             row["prior_total_duration_minutes"],
             row["total_duration_minutes_delta"]), (45, 45, 0))

    # -- JSON, per kind ----------------------------------------------------
    def test_json_parses_and_equals_dict_twin_both_kinds(self):
        for kind, twin in (("staff", export_prior_staff),
                           ("service", export_prior_service)):
            text = self._call(kind=kind, format="json")
            rows = twin(self.salon, START, END)
            self.assertEqual(json.loads(text), _parsed(rows))
            self.assertEqual(text, _expected_json(rows))

    def test_json_staff_pinned(self):
        text = self._call(kind="staff", format="json")
        self.assertEqual(json.loads(text), self._pinned_staff_rows())

    def test_json_rows_equal_csv_rows_both_kinds(self):
        for kind, csv_fn in (("staff", export_prior_staff_csv),
                             ("service", export_prior_service_csv)):
            json_rows = json.loads(self._call(kind=kind, format="json"))
            csv_rows = list(csv.DictReader(io.StringIO(
                csv_fn(self.salon, START, END))))
            self.assertEqual(
                csv_rows,
                [{k: str(v) for k, v in r.items()} for r in json_rows])

    def test_json_via_cli_flag_both_kinds(self):
        for kind, twin in (("staff", export_prior_staff),
                           ("service", export_prior_service)):
            out = io.StringIO()
            call_command("export_prior_staff_service", "--salon-id",
                         str(self.salon.pk), "--kind", kind,
                         "--start-date", START.isoformat(),
                         "--end-date", END.isoformat(), "--format", "json",
                         stdout=out)
            self.assertEqual(out.getvalue(),
                             _expected_json(twin(self.salon, START, END)))

    def test_json_output_file_both_kinds(self):
        for kind, twin in (("staff", export_prior_staff),
                           ("service", export_prior_service)):
            out = io.StringIO()
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "out.json")
                call_command("export_prior_staff_service",
                             salon_id=self.salon.pk, kind=kind,
                             start_date=START, end_date=END,
                             format="json", output=path, stdout=out)
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
            self.assertEqual(
                text, _expected_json(twin(self.salon, START, END)))
            self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical_staff(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            call_command("export_prior_staff_service",
                         salon_id=self.salon.pk, kind="staff",
                         start_date=START, end_date=END, output=path,
                         stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, self._pinned_staff_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_salon_json_and_csv_agree_both_kinds(self):
        for kind, twin, csv_fn, fields in (
                ("staff", export_prior_staff, export_prior_staff_csv,
                 PRIOR_STAFF_FIELDNAMES),
                ("service", export_prior_service, export_prior_service_csv,
                 PRIOR_SERVICE_FIELDNAMES)):
            self.assertEqual(twin(self.other, START, END), [])
            self.assertEqual(csv_fn(self.other, START, END),
                             ",".join(fields) + "\n")
            out = io.StringIO()
            call_command("export_prior_staff_service",
                         salon_id=self.other.pk, kind=kind,
                         start_date=START, end_date=END, format="json",
                         stdout=out)
            self.assertEqual(out.getvalue(), "[]\n")
            self.assertEqual(json.loads(out.getvalue()), [])

    # -- Errors --------------------------------------------------------------
    def test_unknown_format_raises_command_error(self):
        for kind in ("staff", "service"):
            with self.assertRaises(CommandError):
                self._call(kind=kind, format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_prior_staff_service", "--salon-id",
                         str(self.salon.pk), "--kind", "staff",
                         "--start-date", START.isoformat(),
                         "--end-date", END.isoformat(), "--format", "xml",
                         stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_staff_service", salon_id=999999,
                         kind="service", start_date=START, end_date=END,
                         format="json", stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.json")
            with self.assertRaises(CommandError):
                call_command("export_prior_staff_service",
                             salon_id=self.salon.pk, kind="staff",
                             start_date=START, end_date=END, format="json",
                             output=path, stdout=io.StringIO())
