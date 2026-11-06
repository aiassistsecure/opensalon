"""Tests for the insights export_popularity command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_popularity_csv``
service), that JSON parses to the dict rows from the new twin
``export_popularity`` -- the same rows the CSV is built
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
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from insights.popularity_export import (
    POPULARITY_FIELDNAMES,
    export_popularity,
    export_popularity_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)


def _expected_json(salon, start=START, end=END):
    return json.dumps(export_popularity(salon, start, end), indent=2,
                      cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportPopularityFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="C", last_name="Test")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        self.cut = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.colour = Service.objects.create(
            category=category, name="Colour", service_minutes=90)
        for i in range(3):
            self._appt(service=self.cut, day_offset=i)
        self._appt(service=self.cut, day_offset=3,
                   status=Appointment.Status.BOOKED)
        self._appt(service=self.cut, day_offset=4,
                   status=Appointment.Status.CANCELLED)
        self._appt(service=self.cut, day_offset=5,
                   status=Appointment.Status.NO_SHOW)
        self._appt(service=self.colour)
        self._appt(service_name="Legacy Trim")

    def _appt(self, *, service=None, service_name="", day_offset=0,
              status=Appointment.Status.COMPLETED):
        start = datetime.datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
        start = start + timedelta(days=day_offset)
        return Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=service, service_name=service_name,
            start=start, end=start + timedelta(minutes=45),
            status=status)

    def _pinned_csv(self):
        return (
            ",".join(POPULARITY_FIELDNAMES) + "\n"
            f"{self.cut.pk},Haircut,3,1,2,1,1,6\n"
            f"{self.colour.pk},Colour,1,0,0,0,0,1\n"
            ",Legacy Trim,1,0,0,0,0,1\n"
        )

    def _pinned_rows(self):
        return [
            {"service_id": self.cut.pk, "service_name": "Haircut",
             "completed_count": 3, "booked_count": 1,
             "cancelled_no_show_count": 2, "cancelled_count": 1,
             "no_show_count": 1, "total_count": 6},
            {"service_id": self.colour.pk, "service_name": "Colour",
             "completed_count": 1, "booked_count": 0,
             "cancelled_no_show_count": 0, "cancelled_count": 0,
             "no_show_count": 0, "total_count": 1},
            {"service_id": "", "service_name": "Legacy Trim",
             "completed_count": 1, "booked_count": 0,
             "cancelled_no_show_count": 0, "cancelled_count": 0,
             "no_show_count": 0, "total_count": 1},
        ]

    def _call(self, **kwargs):
        out = io.StringIO()
        call_command("export_popularity", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(export_popularity_csv(self.salon, START, END),
                         self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(self._call(),
                         export_popularity_csv(self.salon, START, END))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_popularity", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_popularity(self.salon, START, END)
        self.assertEqual(rows, self._pinned_rows())
        parsed = list(csv.DictReader(io.StringIO(
            export_popularity_csv(self.salon, START, END))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in rows],
            parsed)
        self.assertEqual([list(row) for row in rows],
                         [POPULARITY_FIELDNAMES] * len(rows))

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_popularity(self.salon, START, END)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon))
        self.assertIn("Haircut", text)

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_popularity_csv(self.salon, START, END))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_popularity", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon))

    def test_json_output_file(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "popularity.json")
            call_command("export_popularity", salon_id=self.salon.pk,
                         start_date=START, end_date=END, format="json",
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, _expected_json(self.salon))
        self.assertEqual(json.loads(text),
                         _parsed(export_popularity(self.salon, START, END)))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "popularity.csv")
            call_command("export_popularity", salon_id=self.salon.pk,
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
        call_command("export_popularity", salon_id=self.salon.pk,
                     start_date=start, end_date=end, format="json",
                     stdout=out)
        self.assertEqual(out.getvalue(), "[]\n")
        self.assertEqual(export_popularity(self.salon, start, end), [])
        out = io.StringIO()
        call_command("export_popularity", salon_id=self.salon.pk,
                     start_date=start, end_date=end, stdout=out)
        self.assertEqual(out.getvalue(),
                         ",".join(POPULARITY_FIELDNAMES) + "\n")

    def test_json_scopes_to_salon(self):
        out = io.StringIO()
        call_command("export_popularity", salon_id=self.other.pk,
                     start_date=START, end_date=END, format="json",
                     stdout=out)
        self.assertEqual(out.getvalue(), "[]\n")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_popularity", "--salon-id",
                         str(self.salon.pk), "--start-date",
                         START.isoformat(), "--end-date", END.isoformat(),
                         "--format", "xml", stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_popularity", salon_id=999999,
                         start_date=START, end_date=END, format="json",
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.json")
            with self.assertRaises(CommandError):
                call_command("export_popularity",
                             salon_id=self.salon.pk, start_date=START,
                             end_date=END, format="json", output=path,
                             stdout=io.StringIO())
