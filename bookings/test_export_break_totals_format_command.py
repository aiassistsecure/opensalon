"""Tests for --format on the export_break_totals management command.

CSV (default) must be byte-identical to the service; JSON must
parse and equal break_totals_rows for the same arguments, and
CSV/JSON rows must agree. Fixtures are tiny synthetic records.
"""
import csv
import datetime
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from bookings.break_totals_export import break_totals_rows, export_break_totals_csv
from bookings.models import Break
from saloncore.models import Salon
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
NEXT = DAY + datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class ExportBreakTotalsFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        Break.objects.create(staff_member=self.staff, start=at(DAY, 12),
                             end=at(DAY, 12, 30), paid=True)
        Break.objects.create(staff_member=self.staff, start=at(DAY, 13),
                             end=at(DAY, 14), paid=False)
        Break.objects.create(staff_member=self.staff2, start=at(DAY, 10),
                             end=at(DAY, 10, 15), paid=True)

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command("export_break_totals", salon_id=self.salon.pk,
                     date_from=DAY, stdout=out)
        self.assertEqual(out.getvalue(), export_break_totals_csv(self.salon, DAY, None))

    def test_explicit_csv_matches_service(self):
        out = io.StringIO()
        call_command("export_break_totals", salon_id=self.salon.pk,
                     date_from=DAY, format="csv", stdout=out)
        self.assertEqual(out.getvalue(), export_break_totals_csv(self.salon, DAY, None))
        out = io.StringIO()
        call_command("export_break_totals", "--salon-id", str(self.salon.pk),
                     "--date-from", DAY.isoformat(), "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), export_break_totals_csv(self.salon, DAY, None))

    def test_json_parses_and_equals_rows(self):
        out = io.StringIO()
        call_command("export_break_totals", salon_id=self.salon.pk,
                     date_from=DAY, format="json", stdout=out)
        rows = break_totals_rows(self.salon, DAY, None)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(out.getvalue(),
                         json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_csv_json_row_agreement(self):
        csv_out, json_out = io.StringIO(), io.StringIO()
        call_command("export_break_totals", salon_id=self.salon.pk,
                     date_from=DAY, stdout=csv_out)
        call_command("export_break_totals", salon_id=self.salon.pk,
                     date_from=DAY, format="json", stdout=json_out)
        csv_rows = list(csv.DictReader(io.StringIO(csv_out.getvalue())))
        json_rows = json.loads(json_out.getvalue())
        self.assertEqual(len(csv_rows), len(json_rows))
        for crow, jrow in zip(csv_rows, json_rows):
            self.assertEqual(list(jrow.keys()), list(crow.keys()))
            for key, val in jrow.items():
                self.assertEqual(crow[key], "" if val is None else str(val))

    def test_json_empty(self):
        out = io.StringIO()
        call_command("export_break_totals", salon_id=self.salon.pk,
                     date_from=NEXT, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(out.getvalue(), "[]\n")

    def test_json_filters_compose(self):
        out = io.StringIO()
        call_command("export_break_totals", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY, staff_member=self.staff.pk,
                     format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         break_totals_rows(self.salon, DAY, DAY,
                                           staff_member=self.staff.pk))

    def test_json_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "breaks.json")
            call_command("export_break_totals", salon_id=self.salon.pk,
                         date_from=DAY, format="json", output=path,
                         stdout=io.StringIO())
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        rows = break_totals_rows(self.salon, DAY, None)
        self.assertEqual(written, json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_break_totals", salon_id=self.salon.pk,
                         date_from=DAY, format="xml", stdout=io.StringIO())
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_break_totals", "--salon-id", str(self.salon.pk),
                         "--date-from", DAY.isoformat(), "--format", "xml",
                         stdout=io.StringIO())
