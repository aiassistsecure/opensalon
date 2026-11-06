"""Tests for --format on the export_prior_upcoming command.

CSV (default) must be byte-identical to the service; JSON must
parse and equal the wrapper dict from export_prior_upcoming_dict
for the same arguments, serialised verbatim via
DjangoJSONEncoder (Group B shape (i): the wrapper dict itself,
not the bare rows list), and the wrapper's rows must agree with
the CSV rows. Fixtures are tiny synthetic records.
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
from bookings.prior_upcoming_export import (
    export_prior_upcoming_csv,
    export_prior_upcoming_dict,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 9)  # Monday; forward [Nov 9, Nov 12)
UTC = datetime.timezone.utc


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


def d(n):
    return DAY + datetime.timedelta(days=n)


def _expected_json(payload):
    return json.loads(json.dumps(payload, cls=DjangoJSONEncoder))


class ExportPriorUpcomingFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.one = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.two = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.three = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Three")
        self.four = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Four")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        # Elapsed [Nov 6, Nov 9): Nov6 One x2, Nov7 Two x1,
        # Nov8 Three x1 = 4.
        self._appt(d(-3), 9); self._appt(d(-3), 11)
        self._appt(d(-2), 10, staff=self.two)
        self._appt(d(-1), 10, staff=self.three)
        # Forward [Nov 9, Nov 12): Nov9 One x1, Nov10 One x1 +
        # Two x2, Nov11 Four x1 = 5.
        self._appt(d(0), 9); self._appt(d(1), 9)
        self._appt(d(1), 10, staff=self.two)
        self._appt(d(1), 13, staff=self.two)
        self._appt(d(2), 9, staff=self.four)

    def _appt(self, day, hour, staff=None, **kw):
        s = at(day, hour)
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.one,
            service=self.service, start=s,
            end=s + datetime.timedelta(minutes=45), **kw)

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command("export_prior_upcoming", salon_id=self.salon.pk,
                     start=DAY, days=3, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_upcoming_csv(self.salon, DAY, 3))

    def test_explicit_csv_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_upcoming", salon_id=self.salon.pk,
                     start=DAY, days=3, format="csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_upcoming_csv(self.salon, DAY, 3))
        out = io.StringIO()
        call_command("export_prior_upcoming", "--salon-id", str(self.salon.pk),
                     "--start-date", DAY.isoformat(), "--days", "3",
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_upcoming_csv(self.salon, DAY, 3))

    def test_json_parses_and_equals_wrapper_dict(self):
        out = io.StringIO()
        call_command("export_prior_upcoming", salon_id=self.salon.pk,
                     start=DAY, days=3, format="json", stdout=out)
        payload = export_prior_upcoming_dict(self.salon, DAY, 3)
        parsed = json.loads(out.getvalue())
        # Shape (i): a wrapper dict, not the bare rows list.
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed, _expected_json(payload))
        self.assertEqual(out.getvalue(),
                         json.dumps(payload, indent=2, cls=DjangoJSONEncoder) + "\n")
        self.assertEqual(parsed["salon_id"], self.salon.pk)
        self.assertEqual(parsed["total"]["current"], 5)
        self.assertEqual(parsed["total"]["elapsed"], 4)
        self.assertEqual(len(parsed["rows"]), 8)
        self.assertEqual(parsed["rows"][0]["section"], "total")
        self.assertEqual(parsed["rows"][0]["prior_label"], "elapsed")

    def test_csv_json_row_agreement(self):
        csv_out, json_out = io.StringIO(), io.StringIO()
        call_command("export_prior_upcoming", salon_id=self.salon.pk,
                     start=DAY, days=3, stdout=csv_out)
        call_command("export_prior_upcoming", salon_id=self.salon.pk,
                     start=DAY, days=3, format="json", stdout=json_out)
        csv_rows = list(csv.DictReader(io.StringIO(csv_out.getvalue())))
        json_rows = json.loads(json_out.getvalue())["rows"]
        self.assertEqual(len(csv_rows), len(json_rows))
        for crow, jrow in zip(csv_rows, json_rows):
            self.assertEqual(list(jrow.keys()), list(crow.keys()))
            for key, val in jrow.items():
                if key == "count_percent_change":
                    # CSV renders percents to 2dp; JSON carries the
                    # wrapper value (Decimal -> string, None -> null).
                    expected = "" if val is None else f"{float(val):.2f}"
                else:
                    expected = "" if val is None else str(val)
                self.assertEqual(crow[key], expected)

    def test_json_empty_salon(self):
        empty = Salon.objects.create(name="Empty Salon", timezone="UTC")
        out = io.StringIO()
        call_command("export_prior_upcoming", salon_id=empty.pk,
                     start=DAY, days=3, format="json", stdout=out)
        payload = export_prior_upcoming_dict(empty, DAY, 3)
        self.assertEqual(json.loads(out.getvalue()), _expected_json(payload))
        self.assertEqual(out.getvalue(),
                         json.dumps(payload, indent=2, cls=DjangoJSONEncoder) + "\n")
        self.assertEqual(json.loads(out.getvalue())["total"]["current"], 0)

    def test_json_days_and_aliases_compose(self):
        out = io.StringIO()
        call_command("export_prior_upcoming", "--salon-id", str(self.salon.pk),
                     "--date", DAY.isoformat(), "--horizon-days", "3",
                     "--format", "json", stdout=out)
        payload = export_prior_upcoming_dict(self.salon, DAY, 3)
        self.assertEqual(json.loads(out.getvalue()), _expected_json(payload))
        self.assertEqual(json.loads(out.getvalue())["days"], 3)

    def test_json_output_file(self):
        m = mock.mock_open()
        with mock.patch(
                "bookings.management.commands.export_prior_upcoming.open", m):
            call_command("export_prior_upcoming", salon_id=self.salon.pk,
                         start=DAY, days=3, format="json",
                         output="prior_upcoming.json", stdout=io.StringIO())
        written = "".join(c.args[0] for c in m().write.call_args_list)
        payload = export_prior_upcoming_dict(self.salon, DAY, 3)
        self.assertEqual(written,
                         json.dumps(payload, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_upcoming", salon_id=self.salon.pk,
                         start=DAY, days=3, format="xml",
                         stdout=io.StringIO())
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_prior_upcoming", "--salon-id", str(self.salon.pk),
                         "--start-date", DAY.isoformat(), "--days", "3",
                         "--format", "xml", stdout=io.StringIO())
