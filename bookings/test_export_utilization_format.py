"""Tests for the export_utilization command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_utilization_csv``
service), that JSON parses to the dict rows from the new twin
``export_utilization`` -- the same rows the CSV is built from --
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
from bookings.utilization_export import (
    UTILIZATION_FIELDNAMES,
    export_utilization,
    export_utilization_csv,
    export_utilization_rows,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MON = datetime.date(2026, 11, 2)  # a Monday
TUE = datetime.date(2026, 11, 3)
UTC = datetime.timezone.utc


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


def _cmd():
    return load_command_class("bookings", "export_utilization")


def _expected_json(salon, date_from, date_to=None):
    return json.dumps(export_utilization(salon, date_from, date_to),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportUtilizationFormatTests(TestCase):
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
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=0,
            start_time=datetime.time(9), end_time=datetime.time(17))
        Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(MON, 9), end=at(MON, 13))
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Other Stylist")
        Appointment.objects.create(
            client=self.client, staff_member=other_staff,
            service=self.service, start=at(MON, 10), end=at(MON, 11))

    def _pinned_csv(self):
        return (
            ",".join(UTILIZATION_FIELDNAMES) + "\n"
            f"{self.staff.pk},Stylist One,2026-11-02,2026-11-03,"
            "1,240,480,0.5\n"
            f"{self.staff2.pk},Stylist Two,2026-11-02,2026-11-03,"
            "0,0,0,0.0\n"
        )

    def _pinned_rows(self):
        return [
            {"staff_member_id": self.staff.pk, "staff_name": "Stylist One",
             "start_date": "2026-11-02", "end_date": "2026-11-03",
             "appointment_count": 1, "booked_minutes": 240,
             "rostered_minutes": 480, "utilization": 0.5},
            {"staff_member_id": self.staff2.pk, "staff_name": "Stylist Two",
             "start_date": "2026-11-02", "end_date": "2026-11-03",
             "appointment_count": 0, "booked_minutes": 0,
             "rostered_minutes": 0, "utilization": 0.0},
        ]

    def _call(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("date_from", MON)
        kwargs.setdefault("date_to", TUE)
        call_command(_cmd(), salon_id=self.salon.pk, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_utilization_csv(self.salon, MON, TUE), self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(
            self._call(), export_utilization_csv(self.salon, MON, TUE))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--date-from", MON.isoformat(),
                     "--date-to", TUE.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_utilization(self.salon, MON, TUE)
        self.assertEqual(rows, self._pinned_rows())
        self.assertEqual(export_utilization_rows(self.salon, MON, TUE), rows)
        parsed = list(csv.DictReader(io.StringIO(
            export_utilization_csv(self.salon, MON, TUE))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in rows],
            parsed)
        self.assertEqual([list(row) for row in rows],
                         [UTILIZATION_FIELDNAMES] * len(rows))

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_utilization(self.salon, MON, TUE)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon, MON, TUE))
        self.assertIn("Stylist One", text)

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_utilization_csv(self.salon, MON, TUE))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--date-from", MON.isoformat(),
                     "--date-to", TUE.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon, MON, TUE))

    # File output is verified through a mocked open, as in
    # test_export_staff_day_format: real filesystem writes
    # are blocked in some test environments.
    def test_json_output_file(self):
        out = io.StringIO()
        mocked = mock.mock_open()
        with mock.patch(
                "bookings.management.commands.export_utilization"
                ".open", mocked, create=True):
            call_command(_cmd(), salon_id=self.salon.pk, date_from=MON,
                         date_to=TUE, format="json",
                         output="utilization.json", stdout=out)
        mocked.assert_called_once_with(
            "utilization.json", "w", encoding="utf-8", newline="")
        handle = mocked()
        handle.write.assert_called_once_with(
            _expected_json(self.salon, MON, TUE))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        mocked = mock.mock_open()
        with mock.patch(
                "bookings.management.commands.export_utilization"
                ".open", mocked, create=True):
            call_command(_cmd(), salon_id=self.salon.pk, date_from=MON,
                         date_to=TUE, output="utilization.csv", stdout=out)
        mocked.assert_called_once_with(
            "utilization.csv", "w", encoding="utf-8", newline="")
        handle = mocked()
        handle.write.assert_called_once_with(self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_reversed_range_json_and_csv(self):
        self.assertEqual(export_utilization(self.salon, TUE, MON), [])
        self.assertEqual(
            json.loads(self._call(format="json",
                                  date_from=TUE, date_to=MON)), [])
        self.assertEqual(self._call(format="json",
                                    date_from=TUE, date_to=MON), "[]\n")
        self.assertEqual(
            export_utilization_csv(self.salon, TUE, MON),
            ",".join(UTILIZATION_FIELDNAMES) + "\n")
        self.assertEqual(
            self._call(date_from=TUE, date_to=MON),
            ",".join(UTILIZATION_FIELDNAMES) + "\n")

    def test_single_day_default_date_to(self):
        rows = export_utilization(self.salon, MON)
        self.assertEqual(rows[0]["start_date"], "2026-11-02")
        self.assertEqual(rows[0]["end_date"], "2026-11-02")
        self.assertEqual(rows[0]["rostered_minutes"], 480)

    def test_json_scopes_to_salon(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.other_salon.pk, date_from=MON,
                     date_to=TUE, format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["staff_name"], "Other Stylist")
        self.assertEqual(rows[0]["appointment_count"], 1)
        self.assertEqual(rows[0]["booked_minutes"], 60)

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command(_cmd(), "--salon-id", str(self.salon.pk),
                         "--date-from", MON.isoformat(), "--format", "xml",
                         stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command(_cmd(), salon_id=999999, date_from=MON,
                         format="json", stdout=io.StringIO())

    def test_no_date_from_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command(_cmd(), salon_id=self.salon.pk,
                         format="json", stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        mocked = mock.mock_open()
        mocked.side_effect = OSError("cannot write")
        with mock.patch(
                "bookings.management.commands.export_utilization"
                ".open", mocked, create=True):
            with self.assertRaises(CommandError):
                call_command(_cmd(), salon_id=self.salon.pk, date_from=MON,
                             format="json", output="out.json",
                             stdout=io.StringIO())
