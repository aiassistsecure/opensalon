"""Tests for the export_rebook_rate command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_rebook_rate_csv``
service), that JSON parses to the dict rows from the new twin
``export_rebook_rate_rows`` -- the same rows the CSV is built
from -- serialised with ``DjangoJSONEncoder`` (indent=2 +
trailing newline), and that unknown formats fail cleanly.
Fixtures are tiny synthetic records.
"""
import csv
import datetime
import io
import json
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from bookings.models import Appointment
from bookings.rebook_rate_export import (
    REBOOK_RATE_EXPORT_FIELDNAMES,
    export_rebook_rate,
    export_rebook_rate_csv,
    export_rebook_rate_rows,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 10, 26)
NEXT = DAY + datetime.timedelta(days=1)
LATER = DAY + datetime.timedelta(days=7)
UTC = datetime.timezone.utc


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


def _expected_json(salon, start, end):
    return json.dumps(export_rebook_rate_rows(salon, start, end),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportRebookRateFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        self._book()

    def _client(self, name):
        return Client.objects.create(
            salon=self.salon, first_name=name, last_name="Example")

    def _appt(self, client, start, status, *, staff_member=None):
        return Appointment.objects.create(
            client=client, staff_member=staff_member or self.staff,
            service=self.service, start=start,
            end=start + datetime.timedelta(minutes=45), status=status)

    def _book(self):
        S = Appointment.Status
        a, b = self._client("A"), self._client("B")
        c, d, e = self._client("C"), self._client("D"), self._client("E")
        self._appt(a, at(DAY, 9), S.COMPLETED)
        self._appt(a, at(NEXT, 9), S.BOOKED, staff_member=self.staff2)
        self._appt(b, at(DAY, 10), S.COMPLETED)
        self._appt(b, at(LATER, 10), S.CANCELLED)
        self._appt(c, at(DAY, 11), S.COMPLETED, staff_member=self.staff2)
        self._appt(c, at(LATER, 11), S.COMPLETED, staff_member=self.staff2)
        self._appt(d, at(DAY, 12), S.BOOKED)
        self._appt(e, at(DAY, 13), S.COMPLETED, staff_member=self.staff2)
        self._appt(e, at(LATER, 13), S.NO_SHOW, staff_member=self.staff2)
        # Total: 5 counted, 4 completed, 3 rebooked, rate 75.00.
        # Stylist One: 2 completed, 1 rebooked, 50.00.
        # Stylist Two: 2 completed, 2 rebooked, 100.00.

    def _pinned_rows(self):
        return [
            {"salon_id": self.salon.pk, "start_date": "2026-10-26",
             "end_date": "2026-10-26", "staff_member_id": "",
             "staff_name": "", "total_appointments": 5, "completed": 4,
             "rebooked": 3, "rebook_rate_percent": "75.00"},
            {"salon_id": self.salon.pk, "start_date": "2026-10-26",
             "end_date": "2026-10-26", "staff_member_id": self.staff.pk,
             "staff_name": "Stylist One", "total_appointments": "",
             "completed": 2, "rebooked": 1,
             "rebook_rate_percent": "50.00"},
            {"salon_id": self.salon.pk, "start_date": "2026-10-26",
             "end_date": "2026-10-26", "staff_member_id": self.staff2.pk,
             "staff_name": "Stylist Two", "total_appointments": "",
             "completed": 2, "rebooked": 2,
             "rebook_rate_percent": "100.00"},
        ]

    def _pinned_csv(self):
        lines = [",".join(REBOOK_RATE_EXPORT_FIELDNAMES)]
        for r in self._pinned_rows():
            lines.append(",".join(str(r[f]) for f in
                                  REBOOK_RATE_EXPORT_FIELDNAMES))
        return "\n".join(lines) + "\n"

    def _call(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("date_from", DAY)
        kwargs.setdefault("date_to", DAY)
        call_command("export_rebook_rate", salon_id=self.salon.pk,
                     stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_rebook_rate_csv(self.salon, DAY, DAY), self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(
            self._call(), export_rebook_rate_csv(self.salon, DAY, DAY))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_rebook_rate", "--salon-id", str(self.salon.pk),
                     "--date-from", DAY.isoformat(),
                     "--date-to", DAY.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_twin_mirrors_csv_rows_exactly(self):
        rows = export_rebook_rate_rows(self.salon, DAY, DAY)
        self.assertEqual(rows, self._pinned_rows())
        self.assertEqual(export_rebook_rate(self.salon, DAY, DAY), rows)
        for row in rows:
            self.assertEqual(list(row), REBOOK_RATE_EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(
            export_rebook_rate_csv(self.salon, DAY, DAY))))
        self.assertEqual(
            [{k: str(v) for k, v in r.items()} for r in rows], parsed)

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_rebook_rate_rows(self.salon, DAY, DAY)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon, DAY, DAY))

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_rebook_rate_csv(self.salon, DAY, DAY))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_rebook_rate", "--salon-id", str(self.salon.pk),
                     "--date-from", DAY.isoformat(),
                     "--date-to", DAY.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon, DAY, DAY))

    def test_json_output_file(self):
        m = mock.mock_open()
        with mock.patch(
                "bookings.management.commands.export_rebook_rate.open", m):
            call_command("export_rebook_rate", salon_id=self.salon.pk,
                         date_from=DAY, date_to=DAY, format="json",
                         output="rebook_rate.json", stdout=io.StringIO())
        written = "".join(c.args[0] for c in m().write.call_args_list)
        self.assertEqual(written, _expected_json(self.salon, DAY, DAY))

    def test_csv_output_file_is_byte_identical(self):
        m = mock.mock_open()
        with mock.patch(
                "bookings.management.commands.export_rebook_rate.open", m):
            call_command("export_rebook_rate", salon_id=self.salon.pk,
                         date_from=DAY, date_to=DAY,
                         output="rebook_rate.csv", stdout=io.StringIO())
        written = "".join(c.args[0] for c in m().write.call_args_list)
        self.assertEqual(written, self._pinned_csv())

    def test_empty_salon_json_and_csv(self):
        empty = Salon.objects.create(name="Empty Salon", timezone="UTC")
        rows = export_rebook_rate_rows(empty, DAY, DAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["salon_id"], empty.pk)
        self.assertEqual(rows[0]["staff_member_id"], "")
        self.assertEqual(rows[0]["total_appointments"], 0)
        self.assertEqual(rows[0]["completed"], 0)
        self.assertEqual(rows[0]["rebook_rate_percent"], "")
        out = io.StringIO()
        call_command("export_rebook_rate", salon_id=empty.pk,
                     date_from=DAY, date_to=DAY, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(out.getvalue(), _expected_json(empty, DAY, DAY))
        out = io.StringIO()
        call_command("export_rebook_rate", salon_id=empty.pk,
                     date_from=DAY, date_to=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_rebook_rate_csv(empty, DAY, DAY))

    def test_json_scopes_to_salon(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        other_staff = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        other_client = Client.objects.create(
            salon=other, first_name="Other", last_name="Client")
        other_cat = ServiceCategory.objects.create(salon=other, name="Hair")
        other_service = Service.objects.create(
            category=other_cat, name="Cut", service_minutes=45)
        Appointment.objects.create(
            client=other_client, staff_member=other_staff,
            service=other_service, start=at(DAY, 9),
            end=at(DAY, 9) + datetime.timedelta(minutes=45),
            status=Appointment.Status.COMPLETED)
        out = io.StringIO()
        call_command("export_rebook_rate", salon_id=other.pk,
                     date_from=DAY, date_to=DAY, format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(rows[0]["salon_id"], other.pk)
        self.assertEqual(rows[0]["completed"], 1)
        self.assertEqual(rows[0]["rebooked"], 0)
        main_rows = export_rebook_rate_rows(self.salon, DAY, DAY)
        self.assertEqual(main_rows[0]["completed"], 4)

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_rebook_rate", "--salon-id",
                         str(self.salon.pk), "--date-from", DAY.isoformat(),
                         "--date-to", DAY.isoformat(), "--format", "xml",
                         stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_rebook_rate", salon_id=999999,
                         date_from=DAY, date_to=DAY, format="json",
                         stdout=io.StringIO())

    def test_missing_date_from_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_rebook_rate", salon_id=self.salon.pk,
                         format="json", stdout=io.StringIO())

    def test_reversed_range_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            self._call(date_from=NEXT, date_to=DAY, format="json")

    def test_invalid_date_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_rebook_rate", "--salon-id",
                         str(self.salon.pk), "--date-from", "not-a-date",
                         "--format", "json", stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        m = mock.mock_open()
        m.side_effect = OSError("cannot write")
        with mock.patch(
                "bookings.management.commands.export_rebook_rate.open", m):
            with self.assertRaises(CommandError):
                call_command("export_rebook_rate",
                             salon_id=self.salon.pk, date_from=DAY,
                             date_to=DAY, format="json",
                             output="missing-dir/out.json",
                             stdout=io.StringIO())
