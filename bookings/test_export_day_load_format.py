"""Tests for the export_day_load command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_day_load_csv``
service), that JSON parses to the dict rows from the new twin
``export_day_load`` -- the same rows the CSV is built from --
serialised with ``DjangoJSONEncoder`` (indent=2 + trailing
newline), and that unknown formats fail cleanly.

Note: this command is loaded explicitly via
``load_command_class("bookings", "export_day_load")``
for the same global-namespace reason as the existing command
tests.
"""
import csv
import datetime
import io
import json
import os
import tempfile

from django.core.management import call_command, load_command_class
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from bookings.day_load_export import (
    DAY_LOAD_FIELDNAMES,
    export_day_load,
    export_day_load_csv,
)
from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
EMPTY_DAY = datetime.date(2026, 11, 9)  # the following Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC)


def _cmd():
    return load_command_class("bookings", "export_day_load")


def _expected_json(salon, day):
    return json.dumps(export_day_load(salon, day),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportDayLoadFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(
            name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(DAY, 9), end=at(DAY, 9, 45))
        Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(DAY, 14), end=at(DAY, 15))
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Other Stylist")
        Appointment.objects.create(
            client=self.client, staff_member=other_staff,
            service=self.service, start=at(DAY, 10), end=at(DAY, 11))

    def _pinned_csv(self):
        return (
            ",".join(DAY_LOAD_FIELDNAMES) + "\n"
            f"{self.staff.pk},Stylist One,2,105,"
            f"{at(DAY, 9).isoformat()},{at(DAY, 14).isoformat()},"
            f"{at(DAY, 15).isoformat()}\n"
            f"{self.staff2.pk},Stylist Two,0,0,,,\n"
        )

    def _pinned_rows(self):
        return [
            {"staff_member_id": self.staff.pk, "staff_name": "Stylist One",
             "appointment_count": 2, "booked_minutes": 105,
             "first_start": at(DAY, 9).isoformat(),
             "last_start": at(DAY, 14).isoformat(),
             "last_end": at(DAY, 15).isoformat()},
            {"staff_member_id": self.staff2.pk, "staff_name": "Stylist Two",
             "appointment_count": 0, "booked_minutes": 0,
             "first_start": "", "last_start": "", "last_end": ""},
        ]

    def _call(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("date", DAY)
        call_command(_cmd(), salon_id=self.salon.pk, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_day_load_csv(self.salon, DAY), self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(
            self._call(), export_day_load_csv(self.salon, DAY))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--date", DAY.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_day_load(self.salon, DAY)
        self.assertEqual(rows, self._pinned_rows())
        parsed = list(csv.DictReader(io.StringIO(
            export_day_load_csv(self.salon, DAY))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in rows],
            parsed)
        self.assertEqual([list(row) for row in rows],
                         [DAY_LOAD_FIELDNAMES] * len(rows))

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_day_load(self.salon, DAY)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon, DAY))
        self.assertIn("Stylist One", text)

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_day_load_csv(self.salon, DAY))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--date", DAY.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon, DAY))

    def test_json_output_file(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "day_load.json")
            call_command(_cmd(), salon_id=self.salon.pk, date=DAY,
                         format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, _expected_json(self.salon, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "day_load.csv")
            call_command(_cmd(), salon_id=self.salon.pk, date=DAY,
                         output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                text = fh.read()
        self.assertEqual(text, self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_day_json_and_csv(self):
        zero_rows = [
            {**row, "appointment_count": 0, "booked_minutes": 0,
             "first_start": "", "last_start": "", "last_end": ""}
            for row in self._pinned_rows()]
        self.assertEqual(
            json.loads(self._call(format="json", date=EMPTY_DAY)),
            zero_rows)
        self.assertEqual(
            export_day_load(self.salon, EMPTY_DAY), zero_rows)
        self.assertEqual(
            self._call(date=EMPTY_DAY),
            ",".join(DAY_LOAD_FIELDNAMES) + "\n"
            f"{self.staff.pk},Stylist One,0,0,,,\n"
            f"{self.staff2.pk},Stylist Two,0,0,,,\n")

    def test_date_only_form_empty(self):
        self.assertEqual(export_day_load(EMPTY_DAY), [])
        self.assertEqual(
            export_day_load_csv(EMPTY_DAY),
            ",".join(DAY_LOAD_FIELDNAMES) + "\n")

    def test_json_scopes_to_salon(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.other_salon.pk, date=DAY,
                     format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["staff_name"], "Other Stylist")
        self.assertEqual(rows[0]["appointment_count"], 1)

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command(_cmd(), "--salon-id", str(self.salon.pk),
                         "--date", DAY.isoformat(), "--format", "xml",
                         stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command(_cmd(), salon_id=999999, date=DAY,
                         format="json", stdout=io.StringIO())

    def test_no_date_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command(_cmd(), salon_id=self.salon.pk,
                         format="json", stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.json")
            with self.assertRaises(CommandError):
                call_command(_cmd(), salon_id=self.salon.pk, date=DAY,
                             format="json", output=path,
                             stdout=io.StringIO())
