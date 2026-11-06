"""Tests for the insights export_client_value command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_client_value_csv``
service), that JSON parses to the dict rows from the new twin
``export_client_value`` -- the same rows the CSV is built
from -- serialised with ``DjangoJSONEncoder`` (indent=2 +
trailing newline), and that unknown formats fail cleanly.
"""
import csv
import datetime
import io
import json
import os
import tempfile
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from checkout.models import Sale, SaleItem
from clients.models import Client
from insights.client_value_export import (
    CLIENT_VALUE_FIELDNAMES,
    export_client_value,
    export_client_value_csv,
)
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
START = datetime.date(2026, 11, 2)
END = datetime.date(2026, 11, 8)
HEADER = ",".join(CLIENT_VALUE_FIELDNAMES) + "\n"


def _expected_json(salon, start=START, end=END):
    return json.dumps(export_client_value(salon, start, end), indent=2,
                      cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportClientValueFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.alice = Client.objects.create(
            salon=self.salon, first_name="Alice", last_name="Able")
        self.bob = Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Baker")

    def _sale(self, client=None, *, day, price="50.00"):
        sale = Sale.objects.create(
            salon=self.salon, client=client, status=Sale.Status.COMPLETED)
        stamp = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
        stamp += datetime.timedelta(days=day)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal(price))
        return sale

    def _seed(self):
        self._sale(self.alice, day=0, price="60.00")
        self._sale(self.alice, day=1, price="40.00")
        self._sale(self.bob, day=0, price="150.00")
        self._sale(None, day=1, price="30.00")  # unattributed: no row

    def _pinned_csv(self):
        return (
            HEADER
            + f"{self.bob.pk},Bob Baker,{self.salon.pk},150.00,1\n"
            + f"{self.alice.pk},Alice Able,{self.salon.pk},100.00,2\n"
        )

    def _pinned_rows(self):
        return [
            {"client_id": self.bob.pk, "client_name": "Bob Baker",
             "salon_id": self.salon.pk, "total": "150.00", "sale_count": 1},
            {"client_id": self.alice.pk, "client_name": "Alice Able",
             "salon_id": self.salon.pk, "total": "100.00", "sale_count": 2},
        ]

    def _call(self, **kwargs):
        out = io.StringIO()
        call_command("export_client_value", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self._seed()
        self.assertEqual(export_client_value_csv(self.salon, START, END),
                         self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self._seed()
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(self._call(),
                         export_client_value_csv(self.salon, START, END))

    def test_explicit_csv_format_matches_service(self):
        self._seed()
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        self._seed()
        out = io.StringIO()
        call_command("export_client_value", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        self._seed()
        rows = export_client_value(self.salon, START, END)
        self.assertEqual(rows, self._pinned_rows())
        parsed = list(csv.DictReader(io.StringIO(
            export_client_value_csv(self.salon, START, END))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in rows],
            parsed)
        self.assertEqual([list(row) for row in rows],
                         [CLIENT_VALUE_FIELDNAMES] * len(rows))

    def test_json_parses_and_equals_dict_twin(self):
        self._seed()
        text = self._call(format="json")
        rows = export_client_value(self.salon, START, END)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon))

    def test_json_rows_equal_csv_rows(self):
        self._seed()
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_client_value_csv(self.salon, START, END))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        self._seed()
        out = io.StringIO()
        call_command("export_client_value", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon))
        self.assertEqual(json.loads(out.getvalue()), self._pinned_rows())

    def test_json_output_file(self):
        self._seed()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "client_value.json")
            call_command("export_client_value", salon_id=self.salon.pk,
                         start_date=START, end_date=END, format="json",
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, _expected_json(self.salon))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        self._seed()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "client_value.csv")
            call_command("export_client_value", salon_id=self.salon.pk,
                         start_date=START, end_date=END,
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_salon_json_and_csv(self):
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        self.assertEqual(export_client_value(empty, START, END), [])
        self.assertEqual(export_client_value_csv(empty, START, END), HEADER)
        out = io.StringIO()
        call_command("export_client_value", salon_id=empty.pk,
                     start_date=START, end_date=END, format="json",
                     stdout=out)
        self.assertEqual(out.getvalue(), "[]\n")
        self.assertEqual(json.loads(out.getvalue()), [])
        out = io.StringIO()
        call_command("export_client_value", salon_id=empty.pk,
                     start_date=START, end_date=END, stdout=out)
        self.assertEqual(out.getvalue(), HEADER)

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_client_value", "--salon-id",
                         str(self.salon.pk), "--start-date",
                         START.isoformat(), "--end-date", END.isoformat(),
                         "--format", "xml", stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_client_value", salon_id=999999,
                         start_date=START, end_date=END, format="json",
                         stdout=io.StringIO())
