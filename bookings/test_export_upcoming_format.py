"""Tests for the export_upcoming command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_upcoming_csv``
service), that JSON parses to the dict rows from the new twin
``export_upcoming`` -- the same rows the CSV is built from --
serialised with ``DjangoJSONEncoder`` (indent=2 + trailing
newline), and that unknown formats fail cleanly.
"""
import csv
import datetime
import io
import json
from unittest import mock

from django.core.management import call_command, load_command_class
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from bookings.models import Appointment
from bookings.upcoming_export import (
    UPCOMING_FIELDNAMES,
    export_upcoming,
    export_upcoming_csv,
    export_upcoming_rows,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
EMPTY_DAY = datetime.date(2026, 12, 7)  # a later Monday, no appts
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC)


def _cmd():
    return load_command_class("bookings", "export_upcoming")


def _expected_json(salon, start, days=7):
    return json.dumps(export_upcoming(salon, start, days),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportUpcomingFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(
            name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        # Created late-first so ordering by start is exercised.
        self.late = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(DAY, 14), end=at(DAY, 15),
            origin=Appointment.Origin.PHONE)
        self.early = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(DAY, 9), end=at(DAY, 9, 45),
            origin=Appointment.Origin.ONLINE)
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Other Stylist")
        other_client = Client.objects.create(
            salon=self.other_salon, first_name="Other", last_name="Client")
        self.other_appt = Appointment.objects.create(
            client=other_client, staff_member=other_staff,
            service=self.service, start=at(DAY, 10), end=at(DAY, 11))

    def _pinned_csv(self):
        return (
            ",".join(UPCOMING_FIELDNAMES) + "\n"
            f"{self.early.pk},{self.salon.pk},{self.client.pk},"
            f"Test Example,{self.staff.pk},Stylist One,Haircut,"
            f"{at(DAY, 9).isoformat()},{at(DAY, 9, 45).isoformat()},"
            f"booked,online\n"
            f"{self.late.pk},{self.salon.pk},{self.client.pk},"
            f"Test Example,{self.staff.pk},Stylist One,Haircut,"
            f"{at(DAY, 14).isoformat()},{at(DAY, 15).isoformat()},"
            f"booked,phone\n"
        )

    def _pinned_rows(self):
        return [
            {"id": self.early.pk, "salon_id": self.salon.pk,
             "client_id": self.client.pk, "client_name": "Test Example",
             "staff_member_id": self.staff.pk, "staff_name": "Stylist One",
             "service_name": "Haircut",
             "start": at(DAY, 9).isoformat(),
             "end": at(DAY, 9, 45).isoformat(),
             "status": "booked", "origin": "online"},
            {"id": self.late.pk, "salon_id": self.salon.pk,
             "client_id": self.client.pk, "client_name": "Test Example",
             "staff_member_id": self.staff.pk, "staff_name": "Stylist One",
             "service_name": "Haircut",
             "start": at(DAY, 14).isoformat(),
             "end": at(DAY, 15).isoformat(),
             "status": "booked", "origin": "phone"},
        ]

    def _call(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("start", DAY)
        kwargs.setdefault("days", 7)
        call_command(_cmd(), salon_id=self.salon.pk, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_upcoming_csv(self.salon, DAY, 7), self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(
            self._call(), export_upcoming_csv(self.salon, DAY, 7))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--start-date", DAY.isoformat(), "--days", "7",
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_upcoming(self.salon, DAY, 7)
        self.assertEqual(rows, self._pinned_rows())
        self.assertEqual(export_upcoming_rows(self.salon, DAY, 7), rows)
        parsed = list(csv.DictReader(io.StringIO(
            export_upcoming_csv(self.salon, DAY, 7))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in rows],
            parsed)
        self.assertEqual([list(row) for row in rows],
                         [UPCOMING_FIELDNAMES] * len(rows))

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_upcoming(self.salon, DAY, 7)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon, DAY))
        self.assertIn("Test Example", text)

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_upcoming_csv(self.salon, DAY, 7))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--start-date", DAY.isoformat(), "--days", "7",
                     "--format", "json", stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon, DAY))

    def test_json_output_file(self):
        out = io.StringIO()
        mocked = mock.mock_open()
        with mock.patch(
                "bookings.management.commands.export_upcoming"
                ".open", mocked, create=True):
            call_command(_cmd(), salon_id=self.salon.pk, start=DAY,
                         days=7, format="json", output="upcoming.json",
                         stdout=out)
        mocked.assert_called_once_with(
            "upcoming.json", "w", encoding="utf-8", newline="")
        handle = mocked()
        handle.write.assert_called_once_with(
            _expected_json(self.salon, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        mocked = mock.mock_open()
        with mock.patch(
                "bookings.management.commands.export_upcoming"
                ".open", mocked, create=True):
            call_command(_cmd(), salon_id=self.salon.pk, start=DAY,
                         days=7, output="upcoming.csv", stdout=out)
        mocked.assert_called_once_with(
            "upcoming.csv", "w", encoding="utf-8", newline="")
        handle = mocked()
        handle.write.assert_called_once_with(self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_window_json_and_csv(self):
        self.assertEqual(
            json.loads(self._call(format="json", start=EMPTY_DAY)), [])
        self.assertEqual(export_upcoming(self.salon, EMPTY_DAY, 7), [])
        self.assertEqual(self._call(start=EMPTY_DAY),
                         ",".join(UPCOMING_FIELDNAMES) + "\n")
        self.assertEqual(
            self._call(format="json", start=EMPTY_DAY), "[]\n")

    def test_json_scopes_to_salon(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.other_salon.pk, start=DAY,
                     days=7, format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], self.other_appt.pk)
        self.assertEqual(rows[0]["salon_id"], self.other_salon.pk)
        self.assertEqual(rows[0]["staff_name"], "Other Stylist")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command(_cmd(), "--salon-id", str(self.salon.pk),
                         "--start-date", DAY.isoformat(), "--format", "xml",
                         stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command(_cmd(), salon_id=999999, start=DAY, days=7,
                         format="json", stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        mocked = mock.mock_open()
        mocked.side_effect = OSError("cannot write")
        with mock.patch(
                "bookings.management.commands.export_upcoming"
                ".open", mocked, create=True):
            with self.assertRaises(CommandError):
                call_command(_cmd(), salon_id=self.salon.pk, start=DAY,
                             days=7, format="json", output="out.json",
                             stdout=io.StringIO())
