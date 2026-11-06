"""Tests for the export_prior_rebook_rate command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the
``export_prior_rebook_rate_csv`` service), that JSON parses to
the dict rows from the new twin
``export_prior_rebook_rate_rows`` -- the same rows the CSV is
built from -- serialised with ``DjangoJSONEncoder`` (indent=2 +
trailing newline), and that unknown formats fail cleanly.
Fixtures are tiny synthetic records.
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
from bookings.prior_rebook_rate_export import (
    PRIOR_REBOOK_RATE_EXPORT_FIELDNAMES,
    export_prior_rebook_rate,
    export_prior_rebook_rate_csv,
    export_prior_rebook_rate_rows,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 10, 26)
PRIOR_DAY = DAY - datetime.timedelta(days=1)
NEXT = DAY + datetime.timedelta(days=1)
LATER = DAY + datetime.timedelta(days=14)
UTC = datetime.timezone.utc


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


def _expected_json(salon, start, end):
    return json.dumps(export_prior_rebook_rate_rows(salon, start, end),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportPriorRebookRateFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.staff3 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Three")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        self._book()

    def _book(self):
        S = Appointment.Status
        rows = [
            ("P1", PRIOR_DAY, 9, S.COMPLETED, None), ("P1", LATER, 9, S.BOOKED, None),
            ("P2", PRIOR_DAY, 10, S.COMPLETED, None),
            ("P3", PRIOR_DAY, 11, S.COMPLETED, "s2"), ("P3", LATER, 11, S.COMPLETED, "s2"),
            ("P4", PRIOR_DAY, 12, S.COMPLETED, "s3"),
            ("A", DAY, 9, S.COMPLETED, None), ("A", NEXT, 9, S.BOOKED, "s2"),
            ("B", DAY, 10, S.COMPLETED, None), ("B", LATER, 10, S.CANCELLED, None),
            ("C", DAY, 11, S.COMPLETED, "s2"), ("C", LATER, 11, S.COMPLETED, "s2"),
            ("D", DAY, 12, S.BOOKED, None),
            ("E", DAY, 13, S.COMPLETED, "s2"), ("E", LATER, 13, S.NO_SHOW, "s2"),
        ]
        clients = {}
        for name, day, hour, status, staff in rows:
            if name not in clients:
                clients[name] = Client.objects.create(
                    salon=self.salon, first_name=name, last_name="Example")
            member = {"s2": self.staff2, "s3": self.staff3}.get(staff, self.staff)
            Appointment.objects.create(
                client=clients[name], staff_member=member, service=self.service,
                start=at(day, hour),
                end=at(day, hour) + datetime.timedelta(minutes=45),
                status=status)
        # Prior: completed 4, rebooked 2, rate 50.00.
        # Current: completed 4, rebooked 3, rate 75.00.

    def _row(self, staff_id, staff_name, cc, pc, cd, cpc, cr, pr, rd, rpc,
             crr, prr, rdelta, rpc2):
        return {
            "salon_id": self.salon.pk,
            "current_start_date": "2026-10-26", "current_end_date": "2026-10-26",
            "prior_start_date": "2026-10-25", "prior_end_date": "2026-10-25",
            "staff_member_id": staff_id, "staff_name": staff_name,
            "current_completed": cc, "prior_completed": pc,
            "completed_delta": cd, "completed_percent_change": cpc,
            "current_rebooked": cr, "prior_rebooked": pr,
            "rebooked_delta": rd, "rebooked_percent_change": rpc,
            "current_rebook_rate_percent": crr,
            "prior_rebook_rate_percent": prr,
            "rebook_rate_delta": rdelta, "rebook_rate_percent_change": rpc2,
        }

    def _pinned_rows(self):
        return [
            self._row("", "", 4, 4, 0, "0.00", 3, 2, 1, "50.00",
                      "75.00", "50.00", "25.00", "50.00"),
            self._row(self.staff.pk, "Stylist One", 2, 2, 0, "0.00",
                      1, 1, 0, "0.00", "50.00", "50.00", "0.00", "0.00"),
            self._row(self.staff3.pk, "Stylist Three", 0, 1, -1, "-100.00",
                      0, 0, 0, "", "", "0.00", "", ""),
            self._row(self.staff2.pk, "Stylist Two", 2, 1, 1, "100.00",
                      2, 1, 1, "100.00", "100.00", "100.00", "0.00", "0.00"),
        ]

    def _pinned_csv(self):
        lines = [",".join(PRIOR_REBOOK_RATE_EXPORT_FIELDNAMES)]
        for r in self._pinned_rows():
            lines.append(",".join(str(r[f]) for f in
                                  PRIOR_REBOOK_RATE_EXPORT_FIELDNAMES))
        return "\n".join(lines) + "\n"

    def _call(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("start_date", DAY)
        kwargs.setdefault("end_date", DAY)
        call_command("export_prior_rebook_rate", salon_id=self.salon.pk,
                     stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_prior_rebook_rate_csv(self.salon, DAY, DAY),
            self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(
            self._call(), export_prior_rebook_rate_csv(self.salon, DAY, DAY))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_prior_rebook_rate", "--salon-id",
                     str(self.salon.pk), "--start-date", DAY.isoformat(),
                     "--end-date", DAY.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_twin_mirrors_csv_rows_exactly(self):
        rows = export_prior_rebook_rate_rows(self.salon, DAY, DAY)
        self.assertEqual(rows, self._pinned_rows())
        self.assertEqual(export_prior_rebook_rate(self.salon, DAY, DAY), rows)
        for row in rows:
            self.assertEqual(list(row), PRIOR_REBOOK_RATE_EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(
            export_prior_rebook_rate_csv(self.salon, DAY, DAY))))
        self.assertEqual(
            [{k: str(v) for k, v in r.items()} for r in rows], parsed)

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_prior_rebook_rate_rows(self.salon, DAY, DAY)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon, DAY, DAY))

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_prior_rebook_rate_csv(self.salon, DAY, DAY))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_prior_rebook_rate", "--salon-id",
                     str(self.salon.pk), "--start-date", DAY.isoformat(),
                     "--end-date", DAY.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon, DAY, DAY))

    def test_json_output_file(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_rebook_rate.json")
            call_command("export_prior_rebook_rate", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY, format="json",
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, _expected_json(self.salon, DAY, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_rebook_rate.csv")
            call_command("export_prior_rebook_rate", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY, output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                text = fh.read()
        self.assertEqual(text, self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_salon_json_and_csv(self):
        empty = Salon.objects.create(name="Empty Salon", timezone="UTC")
        rows = export_prior_rebook_rate_rows(empty, DAY, DAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["salon_id"], empty.pk)
        self.assertEqual(rows[0]["staff_member_id"], "")
        self.assertEqual(rows[0]["current_completed"], 0)
        self.assertEqual(rows[0]["completed_percent_change"], "")
        self.assertEqual(rows[0]["current_rebook_rate_percent"], "")
        out = io.StringIO()
        call_command("export_prior_rebook_rate", salon_id=empty.pk,
                     start_date=DAY, end_date=DAY, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(out.getvalue(), _expected_json(empty, DAY, DAY))
        out = io.StringIO()
        call_command("export_prior_rebook_rate", salon_id=empty.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_prior_rebook_rate_csv(empty, DAY, DAY))

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
        call_command("export_prior_rebook_rate", salon_id=other.pk,
                     start_date=DAY, end_date=DAY, format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(rows[0]["salon_id"], other.pk)
        self.assertEqual(rows[0]["current_completed"], 1)
        self.assertEqual(rows[0]["prior_completed"], 0)
        # Main salon unchanged by the other salon's appointment.
        main_rows = export_prior_rebook_rate_rows(self.salon, DAY, DAY)
        self.assertEqual(main_rows[0]["current_completed"], 4)

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_prior_rebook_rate", "--salon-id",
                         str(self.salon.pk), "--start-date", DAY.isoformat(),
                         "--end-date", DAY.isoformat(), "--format", "xml",
                         stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_rebook_rate", salon_id=999999,
                         start_date=DAY, end_date=DAY, format="json",
                         stdout=io.StringIO())

    def test_missing_dates_raise_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_rebook_rate", salon_id=self.salon.pk,
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
                call_command("export_prior_rebook_rate",
                             salon_id=self.salon.pk, start_date=DAY,
                             end_date=DAY, format="json", output=path,
                             stdout=io.StringIO())
