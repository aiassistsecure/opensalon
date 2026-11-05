"""Tests for --format on the export_prior_break_totals command.

CSV (default) must be byte-identical to the service; JSON must
parse and equal the wrapper dict from
export_prior_break_totals_dict for the same arguments, serialised
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

from bookings.models import Break
from bookings.prior_break_totals_export import (
    export_prior_break_totals_csv,
    export_prior_break_totals_dict,
)
from saloncore.models import Salon
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
PRIOR_DAY = DAY - datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


def _expected_json(payload):
    return json.loads(json.dumps(payload, cls=DjangoJSONEncoder))


class ExportPriorBreakTotalsFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.staff3 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Three")
        # Prior: One paid 30 + unpaid 60; Two none.
        self._break(PRIOR_DAY, 12, 30, paid=True)
        self._break(PRIOR_DAY, 13, 60, paid=False)
        # Current: One paid 45 + unpaid 15; Two unpaid 20; Three none.
        self._break(DAY, 12, 45, paid=True)
        self._break(DAY, 13, 15, paid=False)
        self._break(DAY, 12, 20, paid=False, staff=self.staff2)

    def _break(self, day, hour, minutes, paid=False, staff=None):
        start = at(day, hour)
        return Break.objects.create(
            staff_member=staff or self.staff, start=start,
            end=start + datetime.timedelta(minutes=minutes), paid=paid)

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command("export_prior_break_totals", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_break_totals_csv(self.salon, DAY, DAY))

    def test_explicit_csv_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_break_totals", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, format="csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_break_totals_csv(self.salon, DAY, DAY))
        out = io.StringIO()
        call_command("export_prior_break_totals", "--salon-id", str(self.salon.pk),
                     "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_break_totals_csv(self.salon, DAY, DAY))

    def test_json_parses_and_equals_wrapper_dict(self):
        out = io.StringIO()
        call_command("export_prior_break_totals", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, format="json", stdout=out)
        payload = export_prior_break_totals_dict(self.salon, DAY, DAY)
        parsed = json.loads(out.getvalue())
        # Shape (i): a wrapper dict, not the bare rows list.
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed, _expected_json(payload))
        self.assertEqual(out.getvalue(),
                         json.dumps(payload, indent=2, cls=DjangoJSONEncoder) + "\n")
        self.assertEqual(parsed["salon_id"], self.salon.pk)
        self.assertEqual(parsed["break_count"]["current"], 3)
        self.assertEqual(len(parsed["rows"]), 3)  # total + 2 staff
        self.assertEqual(len(parsed["by_staff"]), 2)

    def test_csv_json_row_agreement(self):
        csv_out, json_out = io.StringIO(), io.StringIO()
        call_command("export_prior_break_totals", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=csv_out)
        call_command("export_prior_break_totals", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, format="json", stdout=json_out)
        csv_rows = list(csv.DictReader(io.StringIO(csv_out.getvalue())))
        json_rows = json.loads(json_out.getvalue())["rows"]
        self.assertEqual(len(csv_rows), len(json_rows))
        self.assertEqual(len(json_rows), 3)
        for crow, jrow in zip(csv_rows, json_rows):
            self.assertEqual(list(jrow.keys()), list(crow.keys()))
            for key, val in jrow.items():
                if key.endswith("_percent_change"):
                    # CSV renders percents to 2dp; JSON carries the
                    # wrapper value (Decimal -> string, None -> null).
                    expected = "" if val is None else f"{float(val):.2f}"
                else:
                    expected = "" if val is None else str(val)
                self.assertEqual(crow[key], expected)

    def test_json_empty(self):
        empty = Salon.objects.create(name="Empty Salon", timezone="UTC")
        out = io.StringIO()
        call_command("export_prior_break_totals", salon_id=empty.pk,
                     start_date=DAY, end_date=DAY, format="json", stdout=out)
        payload = export_prior_break_totals_dict(empty, DAY, DAY)
        self.assertEqual(len(payload["rows"]), 1)  # salon total row only
        self.assertEqual(payload["by_staff"], [])
        self.assertEqual(json.loads(out.getvalue()), _expected_json(payload))
        self.assertEqual(out.getvalue(),
                         json.dumps(payload, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_filters_compose(self):
        out = io.StringIO()
        call_command("export_prior_break_totals", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, staff_member=self.staff.pk,
                     format="json", stdout=out)
        payload = export_prior_break_totals_dict(
            self.salon, DAY, DAY, staff_member=self.staff.pk)
        self.assertEqual(json.loads(out.getvalue()), _expected_json(payload))
        self.assertEqual(len(json.loads(out.getvalue())["rows"]), 2)

    def test_json_output_file(self):
        m = mock.mock_open()
        with mock.patch(
                "bookings.management.commands.export_prior_break_totals.open", m):
            call_command("export_prior_break_totals", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY, format="json",
                         output="prior_break_totals.json", stdout=io.StringIO())
        written = "".join(c.args[0] for c in m().write.call_args_list)
        payload = export_prior_break_totals_dict(self.salon, DAY, DAY)
        self.assertEqual(written,
                         json.dumps(payload, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_break_totals", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY, format="xml",
                         stdout=io.StringIO())
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_prior_break_totals", "--salon-id", str(self.salon.pk),
                         "--start-date", DAY.isoformat(),
                         "--end-date", DAY.isoformat(), "--format", "xml",
                         stdout=io.StringIO())
