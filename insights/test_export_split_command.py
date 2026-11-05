import datetime
import io
import json
import os
import tempfile
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.split_export import export_split, export_split_csv
from saloncore.models import Salon

TODAY = datetime.date(2026, 11, 8)


class ExportSplitCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")

    def _sale_with_service(self, amount="85.00"):
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED)
        stamp = datetime.datetime(
            2026, 11, 8, 12, 0, tzinfo=ZoneInfo("UTC"))
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE,
            quantity=1, unit_price=Decimal(amount))
        return sale

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

    def test_default_format_is_csv_byte_identical(self):
        self._sale_with_service()
        out = io.StringIO()
        call_command(
            "export_split", salon_id=self.salon.pk,
            today=TODAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_split_csv(self.salon, today=TODAY))

    def test_explicit_csv_format_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_split", salon_id=self.salon.pk,
            today=TODAY, format="csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_split_csv(self.salon, today=TODAY))

    def test_csv_flag_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_split", "--salon-id", str(self.salon.pk),
            "--today", TODAY.isoformat(), "--format", "csv",
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_split_csv(self.salon, today=TODAY))

    def test_json_output_parses_and_equals_dict_service_rows(self):
        self._sale_with_service()
        out = io.StringIO()
        call_command(
            "export_split", salon_id=self.salon.pk,
            today=TODAY, format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(
            rows, export_split(self.salon, today=TODAY))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["service"], "85.00")
        self.assertEqual(rows[0]["total"], "85.00")

    def test_json_flag_matches_dict_service(self):
        self._sale_with_service()
        out = io.StringIO()
        call_command(
            "export_split", "--salon-id", str(self.salon.pk),
            "--today", TODAY.isoformat(), "--format", "json",
            stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_split(self.salon, today=TODAY))

    def test_json_empty_salon_is_empty_list(self):
        out = io.StringIO()
        call_command(
            "export_split", salon_id=self.salon.pk,
            today=TODAY, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(
            json.loads(out.getvalue()),
            export_split(self.salon, today=TODAY))

    def test_json_output_file_matches_dict_service(self):
        self._sale_with_service()
        fd, path = tempfile.mkstemp(suffix=".json", dir=".")
        os.close(fd)
        try:
            out = io.StringIO()
            call_command(
                "export_split", salon_id=self.salon.pk,
                today=TODAY, format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
            self.assertEqual(
                json.loads(written),
                export_split(self.salon, today=TODAY))
            self.assertEqual(out.getvalue(), "")
        finally:
            os.unlink(path)

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_split", salon_id=self.salon.pk,
                today=TODAY, format="xml", stdout=io.StringIO())

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_split", "--salon-id", str(self.salon.pk),
                "--format", "xml", stdout=io.StringIO())

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
