"""Tests for --format on the export_prior_status_counts command.

CSV (default) must be byte-identical to the service; JSON must
parse and equal the wrapper dict from
export_prior_status_counts_dict for the same arguments, serialised
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
from bookings.prior_status_counts_export import (
    export_prior_status_counts_csv,
    export_prior_status_counts_dict,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # Monday, current window
PRIOR_DAY = DAY - datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


def _expected_json(payload):
    return json.loads(json.dumps(payload, cls=DjangoJSONEncoder))


class ExportPriorStatusCountsFormatCommandTests(TestCase):
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
        # Prior: total 4 — booked 1, completed 2, no_show 1.
        self._appt(PRIOR_DAY, 9, S.BOOKED)
        self._appt(PRIOR_DAY, 10, S.COMPLETED)
        self._appt(PRIOR_DAY, 11, S.COMPLETED)
        self._appt(PRIOR_DAY, 12, S.NO_SHOW)
        # Current: total 6 — booked 2, completed 1, cancelled 1,
        # no_show 2.
        self._appt(DAY, 9, S.BOOKED)
        self._appt(DAY, 10, S.BOOKED)
        self._appt(DAY, 11, S.COMPLETED)
        self._appt(DAY, 12, S.CANCELLED)
        self._appt(DAY, 13, S.NO_SHOW)
        self._appt(DAY, 14, S.NO_SHOW)

    def _appt(self, day, hour, status):
        return Appointment.objects.create(
            client=self.client, staff_member=self.staff, service=self.service,
            start=at(day, hour), end=at(day, hour) + datetime.timedelta(minutes=45),
            status=status)

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command("export_prior_status_counts", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_status_counts_csv(self.salon, DAY, DAY))

    def test_explicit_csv_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_status_counts", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, format="csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_status_counts_csv(self.salon, DAY, DAY))
        out = io.StringIO()
        call_command("export_prior_status_counts", "--salon-id", str(self.salon.pk),
                     "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_status_counts_csv(self.salon, DAY, DAY))

    def test_json_parses_and_equals_wrapper_dict(self):
        out = io.StringIO()
        call_command("export_prior_status_counts", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, format="json", stdout=out)
        payload = export_prior_status_counts_dict(self.salon, DAY, DAY)
        parsed = json.loads(out.getvalue())
        # Shape (i): a wrapper dict, not the bare rows list.
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed, _expected_json(payload))
        self.assertEqual(out.getvalue(),
                         json.dumps(payload, indent=2, cls=DjangoJSONEncoder) + "\n")
        self.assertEqual(parsed["salon_id"], self.salon.pk)
        self.assertEqual(parsed["total"]["current"], 6)
        self.assertEqual(parsed["by_status"]["no_show"]["prior"], 1)
        self.assertEqual(len(parsed["rows"]), 1 + len(Appointment.Status.choices))
        self.assertEqual(parsed["rows"][0]["status"], "total")

    def test_csv_json_row_agreement(self):
        csv_out, json_out = io.StringIO(), io.StringIO()
        call_command("export_prior_status_counts", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=csv_out)
        call_command("export_prior_status_counts", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, format="json", stdout=json_out)
        csv_rows = list(csv.DictReader(io.StringIO(csv_out.getvalue())))
        json_rows = json.loads(json_out.getvalue())["rows"]
        self.assertEqual(len(csv_rows), len(json_rows))
        for crow, jrow in zip(csv_rows, json_rows):
            self.assertEqual(list(jrow.keys()), list(crow.keys()))
            for key, val in jrow.items():
                if key == "percent_change":
                    # CSV renders percents to 2dp; JSON carries the
                    # wrapper value (Decimal -> string, None -> null).
                    expected = "" if val is None else f"{float(val):.2f}"
                else:
                    expected = "" if val is None else str(val)
                self.assertEqual(crow[key], expected)

    def test_json_empty(self):
        empty = Salon.objects.create(name="Empty Salon", timezone="UTC")
        out = io.StringIO()
        call_command("export_prior_status_counts", salon_id=empty.pk,
                     start_date=DAY, end_date=DAY, format="json", stdout=out)
        payload = export_prior_status_counts_dict(empty, DAY, DAY)
        self.assertEqual(json.loads(out.getvalue()), _expected_json(payload))
        self.assertEqual(out.getvalue(),
                         json.dumps(payload, indent=2, cls=DjangoJSONEncoder) + "\n")
        self.assertEqual(json.loads(out.getvalue())["total"]["current"], 0)

    def test_json_date_aliases_compose(self):
        out = io.StringIO()
        call_command("export_prior_status_counts", "--salon-id", str(self.salon.pk),
                     "--date-from", DAY.isoformat(), "--date-to", DAY.isoformat(),
                     "--format", "json", stdout=out)
        payload = export_prior_status_counts_dict(self.salon, DAY, DAY)
        self.assertEqual(json.loads(out.getvalue()), _expected_json(payload))

    def test_json_output_file(self):
        m = mock.mock_open()
        with mock.patch(
                "bookings.management.commands.export_prior_status_counts.open", m):
            call_command("export_prior_status_counts", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY, format="json",
                         output="prior_status_counts.json", stdout=io.StringIO())
        written = "".join(c.args[0] for c in m().write.call_args_list)
        payload = export_prior_status_counts_dict(self.salon, DAY, DAY)
        self.assertEqual(written,
                         json.dumps(payload, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_status_counts", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY, format="xml",
                         stdout=io.StringIO())
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_prior_status_counts", "--salon-id", str(self.salon.pk),
                         "--start-date", DAY.isoformat(),
                         "--end-date", DAY.isoformat(), "--format", "xml",
                         stdout=io.StringIO())
