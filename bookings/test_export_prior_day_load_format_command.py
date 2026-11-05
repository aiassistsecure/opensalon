"""Tests for --format on the export_prior_day_load command.

CSV (default) must be byte-identical to the service; JSON must
parse and equal the wrapper dict from
export_prior_day_load_dict for the same arguments, serialised
verbatim via DjangoJSONEncoder (Group B shape (i): the wrapper
dict itself, not the bare rows list), and the wrapper's rows must
agree with the CSV rows. Fixtures are tiny synthetic records.
"""
import csv
import datetime
import io
import json
from unittest import mock

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from bookings.models import Appointment
from bookings.prior_day_load_export import (
    export_prior_day_load_csv,
    export_prior_day_load_dict,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # Monday
PRIOR = DAY - datetime.timedelta(days=7)
UTC = datetime.timezone.utc
TIME_KEYS = {f"{p}_{f}" for p in ("current", "prior")
             for f in ("first_start", "last_start", "last_end")}


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


def _expected_json(payload):
    return json.loads(json.dumps(payload, cls=DjangoJSONEncoder))


class ExportPriorDayLoadFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.one = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.two = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.three = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Three")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        # Prior: One 2/105, Two 1/60, Three none.
        self._appt(PRIOR, 9, 60)
        self._appt(PRIOR, 11, 45)
        self._appt(PRIOR, 10, 60, staff=self.two)
        # Current: One 3/165, Two none, Three 1/90.
        self._appt(DAY, 9, 45)
        self._appt(DAY, 13, 60)
        self._appt(DAY, 15, 60)
        self._appt(DAY, 10, 90, staff=self.three)

    def _appt(self, day, hour, minutes, staff=None):
        start = at(day, hour)
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.one,
            service=self.service, start=start,
            end=start + datetime.timedelta(minutes=minutes))

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command("export_prior_day_load", salon_id=self.salon.pk,
                     date=DAY, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_day_load_csv(self.salon, DAY))

    def test_explicit_csv_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_day_load", salon_id=self.salon.pk,
                     date=DAY, format="csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_day_load_csv(self.salon, DAY))
        out = io.StringIO()
        call_command("export_prior_day_load", "--salon-id", str(self.salon.pk),
                     "--date", DAY.isoformat(), "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_day_load_csv(self.salon, DAY))

    def test_json_parses_and_equals_wrapper_dict(self):
        out = io.StringIO()
        call_command("export_prior_day_load", salon_id=self.salon.pk,
                     date=DAY, format="json", stdout=out)
        payload = export_prior_day_load_dict(self.salon, DAY)
        parsed = json.loads(out.getvalue())
        # Shape (i): a wrapper dict, not the bare rows list.
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed, _expected_json(payload))
        self.assertEqual(out.getvalue(),
                         json.dumps(payload, indent=2, cls=DjangoJSONEncoder) + "\n")
        self.assertEqual(parsed["salon_id"], self.salon.pk)
        self.assertEqual(parsed["appointment_count"]["current"], 4)
        self.assertEqual(len(parsed["rows"]), 7)  # total + 3 staff + 3 staff_day
        self.assertEqual(len(parsed["by_staff"]), 3)

    def test_csv_json_row_agreement(self):
        csv_out, json_out = io.StringIO(), io.StringIO()
        call_command("export_prior_day_load", salon_id=self.salon.pk,
                     date=DAY, stdout=csv_out)
        call_command("export_prior_day_load", salon_id=self.salon.pk,
                     date=DAY, format="json", stdout=json_out)
        csv_rows = list(csv.DictReader(io.StringIO(csv_out.getvalue())))
        json_rows = json.loads(json_out.getvalue())["rows"]
        self.assertEqual(len(csv_rows), len(json_rows))
        self.assertEqual(len(json_rows), 7)
        for crow, jrow in zip(csv_rows, json_rows):
            self.assertEqual(list(jrow.keys()), list(crow.keys()))
            for key, val in jrow.items():
                if key.endswith("_percent_change"):
                    # CSV renders percents to 2dp; JSON carries the
                    # wrapper value (Decimal -> string, None -> null).
                    expected = "" if val is None else f"{float(val):.2f}"
                elif key in TIME_KEYS and isinstance(val, str) and val.endswith("Z"):
                    # DjangoJSONEncoder renders UTC datetimes with Z;
                    # CSV renders the same instant via isoformat().
                    expected = val[:-1] + "+00:00"
                else:
                    expected = "" if val is None else str(val)
                self.assertEqual(crow[key], expected)

    def test_json_empty(self):
        empty = Salon.objects.create(name="Empty Salon", timezone="UTC")
        out = io.StringIO()
        call_command("export_prior_day_load", salon_id=empty.pk,
                     date=DAY, format="json", stdout=out)
        payload = export_prior_day_load_dict(empty, DAY)
        self.assertEqual(len(payload["rows"]), 1)  # salon total row only
        self.assertEqual(payload["by_staff"], [])
        self.assertEqual(json.loads(out.getvalue()), _expected_json(payload))
        self.assertEqual(out.getvalue(),
                         json.dumps(payload, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_filters_compose(self):
        out = io.StringIO()
        call_command("export_prior_day_load", salon_id=self.salon.pk,
                     start_date=DAY, format="json", stdout=out)
        payload = export_prior_day_load_dict(self.salon, DAY)
        self.assertEqual(json.loads(out.getvalue()), _expected_json(payload))
        self.assertEqual(len(json.loads(out.getvalue())["rows"]), 7)

    def test_json_output_file(self):
        m = mock.mock_open()
        with mock.patch(
                "bookings.management.commands.export_prior_day_load.open", m):
            call_command("export_prior_day_load", salon_id=self.salon.pk,
                         date=DAY, format="json",
                         output="prior_day_load.json", stdout=io.StringIO())
        written = "".join(c.args[0] for c in m().write.call_args_list)
        payload = export_prior_day_load_dict(self.salon, DAY)
        self.assertEqual(written,
                         json.dumps(payload, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_day_load", salon_id=self.salon.pk,
                         date=DAY, format="xml", stdout=io.StringIO())
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_prior_day_load", "--salon-id", str(self.salon.pk),
                         "--date", DAY.isoformat(), "--format", "xml",
                         stdout=io.StringIO())
