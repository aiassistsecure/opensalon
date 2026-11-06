"""Tests for the export_prior_noshow_rate command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the
``export_prior_noshow_rate_csv`` service), that JSON parses to
the dict rows from the new twin
``export_prior_noshow_rate_rows`` -- a one-element list holding
the same row the CSV is built from, from
``export_prior_noshow_rate_row`` -- serialised with
``DjangoJSONEncoder`` (indent=2 + trailing newline), and that
unknown formats fail cleanly. Fixtures are tiny synthetic records.
"""
import csv
import datetime
import io
import json
import os
import tempfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from bookings.models import Appointment
from bookings.prior_noshow_rate_export import (
    PRIOR_NOSHOW_RATE_EXPORT_FIELDNAMES,
    export_prior_noshow_rate,
    export_prior_noshow_rate_csv,
    export_prior_noshow_rate_row,
    export_prior_noshow_rate_rows,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 10, 26)
PRIOR_DAY = DAY - datetime.timedelta(days=1)
NEXT = DAY + datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


def _expected_json(salon, start, end):
    return json.dumps(export_prior_noshow_rate_rows(salon, start, end),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportPriorNoShowRateFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        S = Appointment.Status
        # Prior: total 4, completed 2, no_shows 1, cancelled 1, late 1,
        # no_show_rate 25.00, late_cancel_rate 25.00.
        self._appt(PRIOR_DAY, 9, S.COMPLETED)
        self._appt(PRIOR_DAY, 10, S.NO_SHOW)
        self._appt(PRIOR_DAY, 11, S.COMPLETED)
        self._appt(PRIOR_DAY, 12, S.CANCELLED, updated=at(PRIOR_DAY, 13))
        # Current: total 6, completed 2, no_shows 2, cancelled 1, late 0,
        # no_show_rate 33.33, late_cancel_rate 0.00.
        self._appt(DAY, 9, S.COMPLETED)
        self._appt(DAY, 10, S.NO_SHOW)
        self._appt(DAY, 11, S.NO_SHOW)
        self._appt(DAY, 12, S.COMPLETED)
        self._appt(DAY, 13, S.CANCELLED, updated=at(DAY, 12))
        self._appt(DAY, 14, S.BOOKED)

    def _appt(self, day, hour, status, *, updated=None, staff=None,
              client=None, service=None):
        a = Appointment.objects.create(
            client=client or self.client, staff_member=staff or self.staff,
            service=service or self.service, start=at(day, hour),
            end=at(day, hour) + datetime.timedelta(minutes=45), status=status)
        if updated is not None:
            Appointment.objects.filter(pk=a.pk).update(updated_at=updated)
        return a

    def _pinned_row(self):
        return {
            "salon_id": self.salon.pk,
            "current_start_date": "2026-10-26",
            "current_end_date": "2026-10-26",
            "prior_start_date": "2026-10-25",
            "prior_end_date": "2026-10-25",
            "current_total_appointments": 6, "prior_total_appointments": 4,
            "total_appointments_delta": 2,
            "total_appointments_percent_change": "50.00",
            "current_completed": 2, "prior_completed": 2,
            "completed_delta": 0, "completed_percent_change": "0.00",
            "current_no_shows": 2, "prior_no_shows": 1,
            "no_shows_delta": 1, "no_shows_percent_change": "100.00",
            "current_cancelled": 1, "prior_cancelled": 1,
            "cancelled_delta": 0, "cancelled_percent_change": "0.00",
            "current_late_cancellations": 0, "prior_late_cancellations": 1,
            "late_cancellations_delta": -1,
            "late_cancellations_percent_change": "-100.00",
            "current_no_show_rate_percent": "33.33",
            "prior_no_show_rate_percent": "25.00",
            "no_show_rate_delta": "8.33",
            "no_show_rate_percent_change": "33.32",
            "current_late_cancel_rate_percent": "0.00",
            "prior_late_cancel_rate_percent": "25.00",
            "late_cancel_rate_delta": "-25.00",
            "late_cancel_rate_percent_change": "-100.00",
        }

    def _pinned_csv(self):
        return (
            ",".join(PRIOR_NOSHOW_RATE_EXPORT_FIELDNAMES) + "\n"
            f"{self.salon.pk},2026-10-26,2026-10-26,2026-10-25,2026-10-25,"
            "6,4,2,50.00,2,2,0,0.00,2,1,1,100.00,1,1,0,0.00,"
            "0,1,-1,-100.00,33.33,25.00,8.33,33.32,0.00,25.00,-25.00,-100.00\n"
        )

    def _call(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("start_date", DAY)
        kwargs.setdefault("end_date", DAY)
        call_command("export_prior_noshow_rate", salon_id=self.salon.pk,
                     stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_prior_noshow_rate_csv(self.salon, DAY, DAY),
            self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(
            self._call(), export_prior_noshow_rate_csv(self.salon, DAY, DAY))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_prior_noshow_rate", "--salon-id",
                     str(self.salon.pk), "--start-date", DAY.isoformat(),
                     "--end-date", DAY.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_twin_mirrors_csv_rows_exactly(self):
        row = export_prior_noshow_rate_row(self.salon, DAY, DAY)
        rows = export_prior_noshow_rate_rows(self.salon, DAY, DAY)
        self.assertEqual(row, self._pinned_row())
        self.assertEqual(rows, [row])
        self.assertEqual(export_prior_noshow_rate(self.salon, DAY, DAY), rows)
        self.assertEqual(list(row), PRIOR_NOSHOW_RATE_EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(
            export_prior_noshow_rate_csv(self.salon, DAY, DAY))))
        self.assertEqual(
            [{k: str(v) for k, v in r.items()} for r in rows], parsed)

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_prior_noshow_rate_rows(self.salon, DAY, DAY)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), [self._pinned_row()])
        self.assertEqual(text, _expected_json(self.salon, DAY, DAY))

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_prior_noshow_rate_csv(self.salon, DAY, DAY))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_prior_noshow_rate", "--salon-id",
                     str(self.salon.pk), "--start-date", DAY.isoformat(),
                     "--end-date", DAY.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon, DAY, DAY))

    def test_json_output_file(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_noshow_rate.json")
            call_command("export_prior_noshow_rate", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY, format="json",
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, _expected_json(self.salon, DAY, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_noshow_rate.csv")
            call_command("export_prior_noshow_rate", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY, output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                text = fh.read()
        self.assertEqual(text, self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_salon_json_and_csv(self):
        empty = Salon.objects.create(name="Empty Salon", timezone="UTC")
        row = export_prior_noshow_rate_row(empty, DAY, DAY)
        self.assertEqual(row["salon_id"], empty.pk)
        self.assertEqual(row["current_total_appointments"], 0)
        self.assertEqual(row["total_appointments_percent_change"], "")
        self.assertEqual(row["current_no_show_rate_percent"], "")
        self.assertEqual(row["no_show_rate_percent_change"], "")
        out = io.StringIO()
        call_command("export_prior_noshow_rate", salon_id=empty.pk,
                     start_date=DAY, end_date=DAY, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [row])
        self.assertEqual(out.getvalue(), _expected_json(empty, DAY, DAY))
        out = io.StringIO()
        call_command("export_prior_noshow_rate", salon_id=empty.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_prior_noshow_rate_csv(empty, DAY, DAY))

    def test_json_scopes_to_salon(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        other_staff = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        other_client = Client.objects.create(
            salon=other, first_name="Other", last_name="Client")
        other_cat = ServiceCategory.objects.create(salon=other, name="Hair")
        other_service = Service.objects.create(
            category=other_cat, name="Cut", service_minutes=45)
        self._appt(DAY, 9, Appointment.Status.COMPLETED, staff=other_staff,
                   client=other_client, service=other_service)
        out = io.StringIO()
        call_command("export_prior_noshow_rate", salon_id=other.pk,
                     start_date=DAY, end_date=DAY, format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["salon_id"], other.pk)
        self.assertEqual(rows[0]["current_total_appointments"], 1)
        self.assertEqual(rows[0]["current_completed"], 1)

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_prior_noshow_rate", "--salon-id",
                         str(self.salon.pk), "--start-date", DAY.isoformat(),
                         "--end-date", DAY.isoformat(), "--format", "xml",
                         stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_noshow_rate", salon_id=999999,
                         start_date=DAY, end_date=DAY, format="json",
                         stdout=io.StringIO())

    def test_missing_dates_raise_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_noshow_rate", salon_id=self.salon.pk,
                         format="json", stdout=io.StringIO())

    def test_reversed_range_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            self._call(start_date=NEXT, end_date=DAY, format="json")

    def test_invalid_date_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            self._call(start_date="not-a-date", format="json")

    def test_unwritable_output_raises_command_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.json")
            with self.assertRaises(CommandError):
                call_command("export_prior_noshow_rate",
                             salon_id=self.salon.pk, start_date=DAY,
                             end_date=DAY, format="json", output=path,
                             stdout=io.StringIO())
