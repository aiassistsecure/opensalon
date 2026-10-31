"""Tests for the insights export_returning management command.

The command is a thin wrapper around
``insights.returning_export.export_returning_revenue_csv``:
these tests pin that its stdout and file output match that
service verbatim, and that unknown salons, bad dates, missing
dates, service errors, and unwritable output fail cleanly as
``CommandError``.

These tests load the insights command class explicitly via
``load_command_class("insights", "export_returning")`` and
pass that instance to ``call_command`` — pinning this app's
command, not the global name resolution.
"""
import datetime
import io
import os
import tempfile
from unittest import mock

from django.core.management import CommandError, call_command, load_command_class
from django.test import TestCase

from insights.returning_export import export_returning_revenue_csv
from saloncore.models import Salon

START = datetime.date(2026, 11, 2)
END = datetime.date(2026, 11, 8)


def _cmd():
    return load_command_class("insights", "export_returning")


class ExportReturningCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk,
            start_date=START, end_date=END, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_returning_revenue_csv(self.salon, START, END))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            _cmd(), "--salon-id", str(self.salon.pk),
            "--start-date", START.isoformat(), "--end-date", END.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_returning_revenue_csv(self.salon, START, END))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "returning.csv")
            call_command(
                _cmd(), salon_id=self.salon.pk,
                start_date=START, end_date=END, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_returning_revenue_csv(self.salon, START, END))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), salon_id=self.salon.pk + 999,
                start_date=START, end_date=END, stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), salon_id=self.salon.pk,
                start_date="not-a-date", end_date=END,
                stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), "--salon-id", str(self.salon.pk),
                "--start-date", START.isoformat(),
                "--end-date", "2026-13-40", stdout=io.StringIO())

    def test_missing_dates_raise_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), salon_id=self.salon.pk,
                stdout=io.StringIO())

    def test_service_error_raises_command_error(self):
        with mock.patch(
            "insights.management.commands.export_returning."
            "export_returning_revenue_csv",
            side_effect=ValueError("boom"),
        ):
            with self.assertRaises(CommandError):
                call_command(
                    _cmd(), salon_id=self.salon.pk,
                    start_date=START, end_date=END,
                    stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "returning.csv")
            with self.assertRaises(CommandError):
                call_command(
                    _cmd(), salon_id=self.salon.pk,
                    start_date=START, end_date=END, output=path,
                    stdout=io.StringIO())
