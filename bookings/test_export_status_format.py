"""Tests for the export_status command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_status_counts_csv``
service), that JSON parses to the dict rows from the new twin
``export_status_counts`` -- the same rows the CSV is built from --
serialised with ``DjangoJSONEncoder`` (indent=2 + trailing
newline), and that unknown formats fail cleanly.
Fixtures are tiny synthetic records -- unit logic only.
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
from bookings.status_export import (
    STATUS_EXPORT_FIELDNAMES,
    export_status_counts,
    export_status_counts_csv,
    export_status_counts_rows,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
EMPTY_DAY = datetime.date(2026, 11, 9)  # the following Monday
UTC = datetime.timezone.utc
STATUSES = ["booked", "confirmed", "arrived", "in_service",
            "completed", "cancelled", "no_show"]


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC)


def _cmd():
    return load_command_class("bookings", "export_status")


def _expected_json(salon, day):
    return json.dumps(export_status_counts(salon, day),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportStatusFormatTests(TestCase):
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
        Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(DAY, 9), end=at(DAY, 9, 45))
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Other Stylist")
        other_client = Client.objects.create(
            salon=self.other_salon, first_name="Other", last_name="Client")
        Appointment.objects.create(
            client=other_client, staff_member=other_staff,
            service=self.service, start=at(DAY, 10), end=at(DAY, 11))

    def _rows(self, salon, day, counts, total):
        return [{"salon_id": salon.pk, "start_date": day.isoformat(),
                 "end_date": day.isoformat(), "status": s,
                 "count": counts.get(s, 0), "total": total}
                for s in STATUSES]

    def _pinned_rows(self):
        return self._rows(self.salon, DAY, {"booked": 1}, 1)

    def _pinned_csv(self):
        lines = [",".join(STATUS_EXPORT_FIELDNAMES)]
        for row in self._pinned_rows():
            lines.append(
                f"{row['salon_id']},{row['start_date']},"
                f"{row['end_date']},{row['status']},{row['count']},"
                f"{row['total']}")
        return "\n".join(lines) + "\n"

    def _call(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("date", DAY)
        call_command(_cmd(), salon_id=self.salon.pk, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_status_counts_csv(self.salon, DAY), self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(
            self._call(), export_status_counts_csv(self.salon, DAY))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--date", DAY.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_status_counts(self.salon, DAY)
        self.assertEqual(rows, self._pinned_rows())
        self.assertEqual(export_status_counts_rows(self.salon, DAY), rows)
        parsed = list(csv.DictReader(io.StringIO(
            export_status_counts_csv(self.salon, DAY))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in rows],
            parsed)
        self.assertEqual([list(row) for row in rows],
                         [STATUS_EXPORT_FIELDNAMES] * len(rows))

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_status_counts(self.salon, DAY)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon, DAY))

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_status_counts_csv(self.salon, DAY))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--date", DAY.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon, DAY))

    def test_json_range_passes_through(self):
        last = DAY + datetime.timedelta(days=1)
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk,
                     date_from=DAY, date_to=last, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         _parsed(export_status_counts(
                             self.salon, date_from=DAY, date_to=last)))
        self.assertEqual(json.loads(out.getvalue())[0]["end_date"],
                         last.isoformat())

    # File output is verified through a mocked open, as in
    # test_export_staff_day_format: real filesystem writes are
    # blocked in some test environments.
    def test_json_output_file(self):
        out = io.StringIO()
        mocked = mock.mock_open()
        with mock.patch(
                "bookings.management.commands.export_status"
                ".open", mocked, create=True):
            call_command(_cmd(), salon_id=self.salon.pk, date=DAY,
                         format="json", output="status.json",
                         stdout=out)
        mocked.assert_called_once_with(
            "status.json", "w", encoding="utf-8", newline="")
        handle = mocked()
        handle.write.assert_called_once_with(
            _expected_json(self.salon, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        mocked = mock.mock_open()
        with mock.patch(
                "bookings.management.commands.export_status"
                ".open", mocked, create=True):
            call_command(_cmd(), salon_id=self.salon.pk, date=DAY,
                         output="status.csv", stdout=out)
        mocked.assert_called_once_with(
            "status.csv", "w", encoding="utf-8", newline="")
        handle = mocked()
        handle.write.assert_called_once_with(self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_day_json_and_csv(self):
        zero_rows = self._rows(self.salon, EMPTY_DAY, {}, 0)
        self.assertEqual(
            json.loads(self._call(format="json", date=EMPTY_DAY)),
            zero_rows)
        self.assertEqual(export_status_counts(self.salon, EMPTY_DAY),
                         zero_rows)
        lines = [",".join(STATUS_EXPORT_FIELDNAMES)]
        for row in zero_rows:
            lines.append(
                f"{row['salon_id']},{row['start_date']},"
                f"{row['end_date']},{row['status']},0,0")
        self.assertEqual(self._call(date=EMPTY_DAY),
                         "\n".join(lines) + "\n")

    def test_json_scopes_to_salon(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.other_salon.pk, date=DAY,
                     format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(rows, self._rows(
            self.other_salon, DAY, {"booked": 1}, 1))
        self.assertNotEqual(rows, self._pinned_rows())

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
        mocked = mock.mock_open()
        mocked.side_effect = OSError("cannot write")
        with mock.patch(
                "bookings.management.commands.export_status"
                ".open", mocked, create=True):
            with self.assertRaises(CommandError):
                call_command(_cmd(), salon_id=self.salon.pk, date=DAY,
                             format="json", output="out.json",
                             stdout=io.StringIO())
