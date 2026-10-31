import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from insights.split_export import export_split_csv
from saloncore.models import Salon

TODAY = datetime.date(2026, 11, 8)


class ExportSplitCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_split", salon_id=self.salon.pk,
            today=TODAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_split_csv(self.salon, today=TODAY))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_split", "--salon-id", str(self.salon.pk),
            "--today", TODAY.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_split_csv(self.salon, today=TODAY))

    def test_stdout_defaults_match_service(self):
        out = io.StringIO()
        call_command(
            "export_split", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_split_csv(self.salon, today=None))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "split.csv")
            call_command(
                "export_split", salon_id=self.salon.pk,
                today=TODAY, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_split_csv(self.salon, today=TODAY))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_split", salon_id=self.salon.pk + 999,
                today=TODAY, stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_split", salon_id=self.salon.pk,
                today="not-a-date", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_split", "--salon-id", str(self.salon.pk),
                "--today", "2026-13-40", stdout=io.StringIO())
