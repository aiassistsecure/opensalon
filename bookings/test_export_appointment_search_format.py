"""Tests for the export_appointment_search command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_search_csv``
service), that JSON parses to the dict rows from the new twin
``export_search_appointments`` -- the same rows the CSV is built
from -- serialised with ``DjangoJSONEncoder`` (indent=2 +
trailing newline), and that unknown formats fail cleanly.

Note: this command is loaded explicitly via
``load_command_class("bookings", "export_appointment_search")``
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

from bookings.models import Appointment
from bookings.search_export import (
    SEARCH_EXPORT_FIELDNAMES,
    export_search_appointments,
    export_search_csv,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC)


def _cmd():
    return load_command_class("bookings", "export_appointment_search")


def _expected_json(salon, **kwargs):
    return json.dumps(export_search_appointments(salon, **kwargs),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportAppointmentSearchFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(
            name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.alice = Client.objects.create(
            salon=self.salon, first_name="Alice", last_name="Smith")
        self.bob = Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Jones")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.alice_appt = Appointment.objects.create(
            client=self.alice, staff_member=self.staff,
            service=self.service, start=at(DAY, 9), end=at(DAY, 10),
            status=Appointment.Status.BOOKED)
        self.bob_appt = Appointment.objects.create(
            client=self.bob, staff_member=self.staff2,
            service=self.service, start=at(DAY, 11), end=at(DAY, 12),
            status=Appointment.Status.CONFIRMED)
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Stylist One")
        other_client = Client.objects.create(
            salon=self.other_salon, first_name="Alice", last_name="Smith")
        Appointment.objects.create(
            client=other_client, staff_member=other_staff,
            service=self.service, start=at(DAY, 10), end=at(DAY, 11))

    def _pinned_csv(self):
        return (
            ",".join(SEARCH_EXPORT_FIELDNAMES) + "\n"
            f"{self.alice_appt.pk},Alice Smith,Stylist One,Haircut,"
            f"{at(DAY, 9).isoformat()},{at(DAY, 10).isoformat()},"
            "booked,unknown\n"
            f"{self.bob_appt.pk},Bob Jones,Stylist Two,Haircut,"
            f"{at(DAY, 11).isoformat()},{at(DAY, 12).isoformat()},"
            "confirmed,unknown\n"
        )

    def _pinned_rows(self):
        return [
            {"id": self.alice_appt.pk, "client": "Alice Smith",
             "staff": "Stylist One", "service_name": "Haircut",
             "start": at(DAY, 9).isoformat(),
             "end": at(DAY, 10).isoformat(),
             "status": "booked", "origin": "unknown"},
            {"id": self.bob_appt.pk, "client": "Bob Jones",
             "staff": "Stylist Two", "service_name": "Haircut",
             "start": at(DAY, 11).isoformat(),
             "end": at(DAY, 12).isoformat(),
             "status": "confirmed", "origin": "unknown"},
        ]

    def _call(self, **kwargs):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(export_search_csv(self.salon), self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(self._call(), export_search_csv(self.salon))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_search_appointments(self.salon)
        self.assertEqual(rows, self._pinned_rows())
        parsed = list(csv.DictReader(io.StringIO(
            export_search_csv(self.salon))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in rows],
            parsed)
        self.assertEqual([list(row) for row in rows],
                         [SEARCH_EXPORT_FIELDNAMES] * len(rows))

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_search_appointments(self.salon)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon))
        self.assertIn("Alice Smith", text)

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_search_csv(self.salon))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--format", "json", stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon))

    def test_json_with_filters(self):
        text = self._call(format="json", query="alice",
                          date_from=DAY, date_to=DAY,
                          staff_member=self.staff.pk, status="booked")
        self.assertEqual(json.loads(text), self._pinned_rows()[:1])
        self.assertEqual(text, _expected_json(
            self.salon, query="alice", date_from=DAY, date_to=DAY,
            staff_member=self.staff.pk, status="booked"))

    def test_json_output_file(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "search.json")
            call_command(_cmd(), salon_id=self.salon.pk, format="json",
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, _expected_json(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "search.csv")
            call_command(_cmd(), salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                text = fh.read()
        self.assertEqual(text, self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_search_json_and_csv(self):
        self.assertEqual(
            self._call(format="json", query="no-such-client"), "[]\n")
        self.assertEqual(
            export_search_appointments(self.salon, query="no-such-client"),
            [])
        self.assertEqual(
            self._call(query="no-such-client"),
            ",".join(SEARCH_EXPORT_FIELDNAMES) + "\n")

    def test_json_scopes_to_salon(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.other_salon.pk, format="json",
                     stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["client"], "Alice Smith")
        self.assertNotEqual(rows[0]["id"], self.alice_appt.pk)

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command(_cmd(), "--salon-id", str(self.salon.pk),
                         "--format", "xml", stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command(_cmd(), salon_id=999999, format="json",
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.json")
            with self.assertRaises(CommandError):
                call_command(_cmd(), salon_id=self.salon.pk,
                             format="json", output=path,
                             stdout=io.StringIO())
