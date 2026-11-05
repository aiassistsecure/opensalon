"""Tests for --format on the export_breaks management command.

CSV (default) must be byte-identical to the service; JSON must
parse and equal the dict service rows for the same arguments,
composing with date, staff and paid filters.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.breaks_export import export_breaks, export_breaks_csv
from bookings.models import Break
from saloncore.models import Salon
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
NEXT = DAY + datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class ExportBreaksFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.b1 = Break.objects.create(
            staff_member=self.staff, start=at(DAY, 12),
            end=at(DAY, 12, 30), paid=True)
        self.b2 = Break.objects.create(
            staff_member=self.staff, start=at(DAY, 13),
            end=at(DAY, 14), paid=False)

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command("export_breaks", salon_id=self.salon.pk,
                     date_from=DAY, stdout=out)
        self.assertEqual(out.getvalue(), export_breaks_csv(self.salon, DAY, None))

    def test_explicit_csv_matches_service(self):
        out = io.StringIO()
        call_command("export_breaks", salon_id=self.salon.pk,
                     date_from=DAY, format="csv", stdout=out)
        self.assertEqual(out.getvalue(), export_breaks_csv(self.salon, DAY, None))
        out = io.StringIO()
        call_command(
            "export_breaks", "--salon-id", str(self.salon.pk),
            "--date-from", DAY.isoformat(), "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), export_breaks_csv(self.salon, DAY, None))

    def test_json_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command("export_breaks", salon_id=self.salon.pk,
                     date_from=DAY, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         export_breaks(self.salon, DAY, None))
        out = io.StringIO()
        call_command(
            "export_breaks", "--salon-id", str(self.salon.pk),
            "--date-from", DAY.isoformat(), "--format", "json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         export_breaks(self.salon, DAY, None))

    def test_json_no_range_and_empty(self):
        out = io.StringIO()
        call_command("export_breaks", salon_id=self.salon.pk,
                     format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         export_breaks(self.salon, None, None))
        out = io.StringIO()
        call_command("export_breaks", salon_id=self.salon.pk,
                     date_from=NEXT, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])

    def test_json_filters_compose(self):
        out = io.StringIO()
        call_command("export_breaks", salon_id=self.salon.pk,
                     date_from=DAY, paid_only=True, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         export_breaks(self.salon, DAY, paid=True))
        out = io.StringIO()
        call_command(
            "export_breaks", "--salon-id", str(self.salon.pk),
            "--date-from", DAY.isoformat(), "--unpaid-only",
            "--format", "json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         export_breaks(self.salon, DAY, paid=False))
        out = io.StringIO()
        call_command("export_breaks", salon_id=self.salon.pk,
                     date_from=DAY, staff_member=self.staff.pk,
                     format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_breaks(self.salon, DAY, staff_member=self.staff.pk))

    def test_json_output_file_matches_dict_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "breaks.json")
            call_command("export_breaks", salon_id=self.salon.pk,
                         date_from=DAY, format="json", output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(json.loads(written), export_breaks(self.salon, DAY, None))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_breaks", salon_id=self.salon.pk,
                         format="xml", stdout=io.StringIO())
        with self.assertRaises((CommandError, SystemExit)):
            call_command(
                "export_breaks", "--salon-id", str(self.salon.pk),
                "--format", "xml", stdout=io.StringIO())
