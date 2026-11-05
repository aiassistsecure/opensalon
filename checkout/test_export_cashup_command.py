"""Tests for the export_cashup management command.

The command is a thin wrapper around
``checkout.cashup_export.export_cashups_csv`` and
``checkout.cashup_export.export_cashups``: these tests
pin that its stdout and file output match those services
verbatim, that the default format is CSV, that JSON output
parses and equals the dict service rows, and that unknown
salons, bad dates, reversed ranges, and unknown formats fail
cleanly as ``CommandError``. Fixtures are tiny synthetic
records -- unit logic only.
"""
import datetime
import io
import json
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.cashup_export import export_cashups, export_cashups_csv
from checkout.models import Cashup
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)
NEXT = DAY + datetime.timedelta(days=1)


def _stamp(day, hour=9):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, 0)),
        datetime.timezone.utc)


class ExportCashupCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        Cashup.objects.create(
            salon=self.salon, period_start=_stamp(DAY, 9),
            period_end=_stamp(DAY, 17),
            tender_totals={"cash": "100.00", "external": "50.00"},
            total=Decimal("150.00"), note="midday")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_cashup", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_cashups_csv(self.salon, DAY, DAY))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_cashup", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", NEXT.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_cashups_csv(self.salon, DAY, NEXT))

    def test_stdout_single_day_when_end_date_omitted(self):
        out = io.StringIO()
        call_command(
            "export_cashup", salon_id=self.salon.pk,
            start_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_cashups_csv(self.salon, DAY, None))
        self.assertEqual(
            out.getvalue(), export_cashups_csv(self.salon, DAY))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cashup.csv")
            call_command(
                "export_cashup", salon_id=self.salon.pk,
                start_date=DAY, end_date=NEXT, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_cashups_csv(self.salon, DAY, NEXT))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_cashup", salon_id=self.salon.pk + 999,
                start_date=DAY, end_date=DAY, stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_cashup", salon_id=self.salon.pk,
                start_date="not-a-date", end_date=DAY,
                stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_cashup", "--salon-id", str(self.salon.pk),
                "--start-date", "2026-13-40",
                "--end-date", DAY.isoformat(), stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_cashup", salon_id=self.salon.pk,
                start_date=NEXT, end_date=DAY, stdout=io.StringIO())

    def test_default_is_csv_byte_identical(self):
        default_out = io.StringIO()
        call_command(
            "export_cashup", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=default_out)
        csv_out = io.StringIO()
        call_command(
            "export_cashup", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, format="csv", stdout=csv_out)
        self.assertEqual(default_out.getvalue(), csv_out.getvalue())
        self.assertEqual(
            default_out.getvalue(),
            export_cashups_csv(self.salon, DAY, DAY))

    def test_explicit_csv_via_cli_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_cashup", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            "--format", "csv", stdout=out)
        self.assertEqual(
            out.getvalue(), export_cashups_csv(self.salon, DAY, DAY))

    def test_json_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command(
            "export_cashup", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_cashups(self.salon, DAY, DAY))
        self.assertEqual(len(json.loads(out.getvalue())), 1)

    def test_json_via_cli_matches_dict_service(self):
        out = io.StringIO()
        call_command(
            "export_cashup", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", NEXT.isoformat(),
            "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_cashups(self.salon, DAY, NEXT))

    def test_json_single_day_when_end_date_omitted(self):
        out = io.StringIO()
        call_command(
            "export_cashup", salon_id=self.salon.pk,
            start_date=DAY, format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_cashups(self.salon, DAY, None))
        self.assertEqual(
            json.loads(out.getvalue()), export_cashups(self.salon, DAY))

    def test_json_output_file_parses_and_equals_dict_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cashups.json")
            call_command(
                "export_cashup", salon_id=self.salon.pk,
                start_date=DAY, end_date=DAY, format="json",
                output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written), export_cashups(self.salon, DAY, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_cashup", salon_id=self.salon.pk,
                start_date=DAY, end_date=DAY, format="xml",
                stdout=io.StringIO())

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_cashup", "--salon-id", str(self.salon.pk),
                "--start-date", DAY.isoformat(),
                "--end-date", DAY.isoformat(),
                "--format", "xml", stdout=io.StringIO())
