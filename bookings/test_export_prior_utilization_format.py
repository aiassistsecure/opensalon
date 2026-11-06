"""Tests for the export_prior_utilization command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the
``export_prior_utilization_csv`` service), that JSON parses to
the dict rows from the new twin
``export_prior_utilization_rows`` -- the same rows the CSV is
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
from bookings.prior_utilization_export import (
    PRIOR_UTILIZATION_EXPORT_FIELDNAMES,
    export_prior_utilization,
    export_prior_utilization_csv,
    export_prior_utilization_rows,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MON = datetime.date(2026, 11, 2)
SUN = MON - datetime.timedelta(days=1)
TUE = MON + datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


def _expected_json(salon, start, end):
    return json.dumps(export_prior_utilization_rows(salon, start, end),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportPriorUtilizationFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.staff3 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Three")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        self._book()

    def _pattern(self, staff, weekday, end_hour=17):
        return RosterPattern.objects.create(
            staff_member=staff, weekday=weekday,
            start_time=datetime.time(9), end_time=datetime.time(end_hour))

    def _appt(self, day, start_hour, end_hour, staff=None):
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.staff,
            service=self.service, start=at(day, start_hour),
            end=at(day, end_hour))

    def _book(self):
        for staff, end in ((self.staff, 17), (self.staff2, 13)):
            self._pattern(staff, 6, end)
            self._pattern(staff, 0, end)
        self._appt(SUN, 9, 13)
        self._appt(MON, 9, 12)
        self._appt(MON, 13, 16)
        self._appt(MON, 9, 11, staff=self.staff2)
        # Prior totals: count 1, booked 240, rostered 720, util 1/3.
        # Current totals: count 3, booked 480, rostered 720, util 2/3.

    def _row(self, staff_id, staff_name, cc, pc, cd, cpc, cb, pb, bd, bpc,
             cr, pr, rd, rpc, cu, pu, ud, upc):
        return {
            "salon_id": self.salon.pk,
            "current_start_date": "2026-11-02", "current_end_date": "2026-11-02",
            "prior_start_date": "2026-11-01", "prior_end_date": "2026-11-01",
            "staff_member_id": staff_id, "staff_name": staff_name,
            "current_appointment_count": cc, "prior_appointment_count": pc,
            "appointment_count_delta": cd,
            "appointment_count_percent_change": cpc,
            "current_booked_minutes": cb, "prior_booked_minutes": pb,
            "booked_minutes_delta": bd, "booked_minutes_percent_change": bpc,
            "current_rostered_minutes": cr, "prior_rostered_minutes": pr,
            "rostered_minutes_delta": rd,
            "rostered_minutes_percent_change": rpc,
            "current_utilization": cu, "prior_utilization": pu,
            "utilization_delta": ud, "utilization_percent_change": upc,
        }

    def _pinned_rows(self):
        return [
            self._row("", "", 3, 1, 2, "200.00", 480, 240, 240, "100.00",
                      720, 720, 0, "0.00",
                      "0.6667", "0.3333", "0.3333", "100.00"),
            self._row(self.staff.pk, "Stylist One", 2, 1, 1, "100.00",
                      360, 240, 120, "50.00", 480, 480, 0, "0.00",
                      "0.7500", "0.5000", "0.2500", "50.00"),
            self._row(self.staff3.pk, "Stylist Three", 0, 0, 0, "",
                      0, 0, 0, "", 0, 0, 0, "",
                      "0.0000", "0.0000", "0.0000", ""),
            self._row(self.staff2.pk, "Stylist Two", 1, 0, 1, "",
                      120, 0, 120, "", 240, 240, 0, "0.00",
                      "0.5000", "0.0000", "0.5000", ""),
        ]

    def _pinned_csv(self):
        lines = [",".join(PRIOR_UTILIZATION_EXPORT_FIELDNAMES)]
        for r in self._pinned_rows():
            lines.append(",".join(str(r[f]) for f in
                                  PRIOR_UTILIZATION_EXPORT_FIELDNAMES))
        return "\n".join(lines) + "\n"

    def _call(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("start_date", MON)
        kwargs.setdefault("end_date", MON)
        call_command("export_prior_utilization", salon_id=self.salon.pk,
                     stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_prior_utilization_csv(self.salon, MON, MON),
            self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(
            self._call(), export_prior_utilization_csv(self.salon, MON, MON))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_prior_utilization", "--salon-id",
                     str(self.salon.pk), "--start-date", MON.isoformat(),
                     "--end-date", MON.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_twin_mirrors_csv_rows_exactly(self):
        rows = export_prior_utilization_rows(self.salon, MON, MON)
        self.assertEqual(rows, self._pinned_rows())
        self.assertEqual(export_prior_utilization(self.salon, MON, MON), rows)
        for row in rows:
            self.assertEqual(list(row), PRIOR_UTILIZATION_EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(
            export_prior_utilization_csv(self.salon, MON, MON))))
        self.assertEqual(
            [{k: str(v) for k, v in r.items()} for r in rows], parsed)

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_prior_utilization_rows(self.salon, MON, MON)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon, MON, MON))

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_prior_utilization_csv(self.salon, MON, MON))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_prior_utilization", "--salon-id",
                     str(self.salon.pk), "--start-date", MON.isoformat(),
                     "--end-date", MON.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon, MON, MON))

    def test_json_output_file(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_utilization.json")
            call_command("export_prior_utilization", salon_id=self.salon.pk,
                         start_date=MON, end_date=MON, format="json",
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, _expected_json(self.salon, MON, MON))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_utilization.csv")
            call_command("export_prior_utilization", salon_id=self.salon.pk,
                         start_date=MON, end_date=MON, output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                text = fh.read()
        self.assertEqual(text, self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_salon_json_and_csv(self):
        empty = Salon.objects.create(name="Empty Salon", timezone="UTC")
        rows = export_prior_utilization_rows(empty, MON, MON)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["salon_id"], empty.pk)
        self.assertEqual(rows[0]["staff_member_id"], "")
        self.assertEqual(rows[0]["current_appointment_count"], 0)
        self.assertEqual(rows[0]["appointment_count_percent_change"], "")
        self.assertEqual(rows[0]["current_utilization"], "0.0000")
        out = io.StringIO()
        call_command("export_prior_utilization", salon_id=empty.pk,
                     start_date=MON, end_date=MON, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(out.getvalue(), _expected_json(empty, MON, MON))
        out = io.StringIO()
        call_command("export_prior_utilization", salon_id=empty.pk,
                     start_date=MON, end_date=MON, stdout=out)
        self.assertEqual(
            out.getvalue(), export_prior_utilization_csv(empty, MON, MON))

    def test_json_scopes_to_salon(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        other_staff = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        RosterPattern.objects.create(
            staff_member=other_staff, weekday=0,
            start_time=datetime.time(9), end_time=datetime.time(17))
        other_client = Client.objects.create(
            salon=other, first_name="Other", last_name="Client")
        other_cat = ServiceCategory.objects.create(salon=other, name="Hair")
        other_service = Service.objects.create(
            category=other_cat, name="Cut", service_minutes=45)
        Appointment.objects.create(
            client=other_client, staff_member=other_staff,
            service=other_service, start=at(MON, 9), end=at(MON, 11))
        out = io.StringIO()
        call_command("export_prior_utilization", salon_id=other.pk,
                     start_date=MON, end_date=MON, format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(rows[0]["salon_id"], other.pk)
        self.assertEqual(rows[0]["current_appointment_count"], 1)
        self.assertEqual(rows[0]["prior_appointment_count"], 0)
        main_rows = export_prior_utilization_rows(self.salon, MON, MON)
        self.assertEqual(main_rows[0]["current_appointment_count"], 3)

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_prior_utilization", "--salon-id",
                         str(self.salon.pk), "--start-date", MON.isoformat(),
                         "--end-date", MON.isoformat(), "--format", "xml",
                         stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_utilization", salon_id=999999,
                         start_date=MON, end_date=MON, format="json",
                         stdout=io.StringIO())

    def test_missing_dates_raise_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_utilization", salon_id=self.salon.pk,
                         format="json", stdout=io.StringIO())

    def test_reversed_range_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            self._call(start_date=TUE, end_date=MON, format="json")

    def test_invalid_date_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            self._call(start_date="not-a-date", format="json")

    def test_unwritable_output_raises_command_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.json")
            with self.assertRaises(CommandError):
                call_command("export_prior_utilization",
                             salon_id=self.salon.pk, start_date=MON,
                             end_date=MON, format="json", output=path,
                             stdout=io.StringIO())
