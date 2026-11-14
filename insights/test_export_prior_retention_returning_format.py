"""Tests for export_prior_retention_returning --format.

Pins that CSV output is byte-identical to the historical
output (the per-kind ``*_csv`` services), that JSON parses
to the dict rows from the new per-kind dict twins -- the
same rows the CSVs are built from -- serialised with
``DjangoJSONEncoder`` (indent=2 + trailing newline) per
selected ``--kind``, and that unknown formats fail cleanly.
"""
import csv
import io
import json
import os
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
from insights.prior_retention_returning_export import (
    PRIOR_RETENTION_FIELDNAMES, PRIOR_RETURNING_FIELDNAMES,
    export_prior_retention, export_prior_retention_csv,
    export_prior_returning, export_prior_returning_csv)
from saloncore.models import Salon
from team.models import StaffMember

UTC = ZoneInfo("UTC")
START, END = date(2026, 11, 2), date(2026, 11, 8)


def _expected_json(rows):
    return json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n"


class ExportPriorRetentionReturningFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Alice")
        self.clients = {
            n: Client.objects.create(
                salon=self.salon, first_name=n, last_name="T")
            for n in ("A", "B", "C", "D", "Ret", "NewP", "NewC")}
        self._seed_retention()
        self._seed_returning()

    def _appt(self, client, day):
        start = datetime(day.year, day.month, day.day, 10, 0, tzinfo=UTC)
        return Appointment.objects.create(
            client=client, staff_member=self.staff, start=start,
            end=start + timedelta(minutes=45),
            status=Appointment.Status.COMPLETED)

    def _sale(self, day, client=None, price="0.00"):
        sale = Sale.objects.create(
            salon=self.salon, client=client,
            status=Sale.Status.COMPLETED)
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        if Decimal(price):
            SaleItem.objects.create(
                sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
                unit_price=Decimal(price))
        return sale

    def _seed_retention(self):
        for n, days in (("A", (2, 4)), ("B", (3, 5))):
            for d in days:
                self._appt(self.clients[n], date(2026, 11, d))
        for n in ("A", "B", "C", "D"):
            self._appt(self.clients[n], date(2026, 10, 28))

    def _seed_returning(self):
        self._sale(date(2026, 10, 20), self.clients["Ret"], "999.00")
        self._sale(date(2026, 10, 28), self.clients["Ret"], "100.00")
        self._sale(date(2026, 11, 4), self.clients["Ret"], "150.00")
        self._sale(date(2026, 10, 28), self.clients["NewP"], "50.00")
        self._sale(date(2026, 11, 4), self.clients["NewC"], "60.00")
        self._sale(date(2026, 11, 3), None, "30.00")
        self._sale(date(2026, 10, 27), None, "10.00")

    def _call(self, kind="retention", **kwargs):
        out = io.StringIO()
        call_command("export_prior_retention_returning",
                     salon_id=self.salon.pk, kind=kind,
                     start_date=START, end_date=END, stdout=out,
                     **kwargs)
        return out.getvalue()

    def test_dict_rows_mirror_csv_rows_for_both_kinds(self):
        for rows_fn, csv_fn, fields in (
                (export_prior_retention, export_prior_retention_csv,
                 PRIOR_RETENTION_FIELDNAMES),
                (export_prior_returning, export_prior_returning_csv,
                 PRIOR_RETURNING_FIELDNAMES)):
            rows = rows_fn(self.salon, START, END)
            self.assertEqual([list(r) for r in rows],
                             [fields] * len(rows))
            parsed = list(csv.DictReader(io.StringIO(
                csv_fn(self.salon, START, END))))
            self.assertEqual(rows, parsed)

    def test_dict_row_values_for_both_kinds(self):
        ret = {r["metric"]: r for r in
               export_prior_retention(self.salon, START, END)}
        self.assertEqual(
            (ret["active_clients"]["current"],
             ret["active_clients"]["prior"],
             ret["active_clients"]["percent_change"]),
            ("2", "4", "-50.00"))
        self.assertEqual(ret["repeat_rate"]["current"], "1.0000")
        self.assertEqual(ret["repeat_clients"]["percent_change"], "")
        retg = {r["metric"]: r for r in
                export_prior_returning(self.salon, START, END)}
        self.assertEqual(
            (retg["total"]["current"], retg["total"]["prior"],
             retg["total"]["delta"], retg["total"]["percent_change"]),
            ("240.00", "160.00", "80.00", "50.00"))
        self.assertEqual(retg["total_sale_count"]["current"], "3")

    def test_default_and_explicit_csv_byte_identical_both_kinds(self):
        for kind, csv_fn in (
                ("retention", export_prior_retention_csv),
                ("returning", export_prior_returning_csv)):
            want = csv_fn(self.salon, START, END)
            self.assertEqual(self._call(kind=kind), want)
            self.assertEqual(self._call(kind=kind, format="csv"), want)

    def test_csv_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_prior_retention_returning",
                     "--salon-id", str(self.salon.pk),
                     "--kind", "returning",
                     "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(),
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_returning_csv(
                             self.salon, START, END))

    def test_json_parses_and_equals_dict_twin_both_kinds(self):
        for kind, rows_fn in (
                ("retention", export_prior_retention),
                ("returning", export_prior_returning)):
            rows = rows_fn(self.salon, START, END)
            text = self._call(kind=kind, format="json")
            self.assertEqual(json.loads(text), rows)
            self.assertEqual(text, _expected_json(rows))

    def test_json_rows_equal_csv_rows_both_kinds(self):
        for kind, csv_fn in (
                ("retention", export_prior_retention_csv),
                ("returning", export_prior_returning_csv)):
            json_rows = json.loads(self._call(kind=kind, format="json"))
            csv_rows = list(csv.DictReader(io.StringIO(
                csv_fn(self.salon, START, END))))
            self.assertEqual(json_rows, csv_rows)

    def test_json_via_cli_flag_per_kind(self):
        out = io.StringIO()
        call_command("export_prior_retention_returning",
                     "--salon-id", str(self.salon.pk),
                     "--kind", "retention",
                     "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(),
                     "--format", "json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         export_prior_retention(self.salon, START, END))

    def test_json_and_csv_output_files(self):
        # __file__-anchored paths: tempfile is broken on this
        # box (/tmp collisions), as in the sibling test module.
        base = os.path.dirname(os.path.abspath(__file__))
        for kind, rows_fn, csv_fn, suffix in (
                ("retention", export_prior_retention,
                 export_prior_retention_csv, "ret"),
                ("returning", export_prior_returning,
                 export_prior_returning_csv, "retg")):
            for fmt, want in (
                    ("json", _expected_json(rows_fn(
                        self.salon, START, END))),
                    ("csv", csv_fn(self.salon, START, END))):
                path = os.path.join(
                    base, f"prior_ret_format_{suffix}.{fmt}")
                try:
                    out = io.StringIO()
                    call_command(
                        "export_prior_retention_returning",
                        salon_id=self.salon.pk, kind=kind,
                        start_date=START, end_date=END, format=fmt,
                        output=path, stdout=out)
                    with open(path, encoding="utf-8") as fh:
                        self.assertEqual(fh.read(), want)
                    self.assertEqual(out.getvalue(), "")
                finally:
                    if os.path.exists(path):
                        os.remove(path)

    def test_empty_salon_json_and_csv_agree_both_kinds(self):
        for kind, rows_fn in (
                ("retention", export_prior_retention),
                ("returning", export_prior_returning)):
            rows = rows_fn(self.other, START, END)
            out = io.StringIO()
            call_command("export_prior_retention_returning",
                         salon_id=self.other.pk, kind=kind,
                         start_date=START, end_date=END,
                         format="json", stdout=out)
            self.assertEqual(json.loads(out.getvalue()), rows)

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_prior_retention_returning",
                         "--salon-id", str(self.salon.pk),
                         "--start-date", START.isoformat(),
                         "--end-date", END.isoformat(),
                         "--format", "xml", stdout=io.StringIO())

    def test_unknown_salon_and_reversed_raise_json(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_retention_returning",
                         salon_id=999999, start_date=START,
                         end_date=END, format="json",
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_retention_returning",
                         salon_id=self.salon.pk, start_date=END,
                         end_date=START, format="json",
                         stdout=io.StringIO())
