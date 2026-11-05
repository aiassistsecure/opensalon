import csv
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
from insights.busiest_revenue_export import (
    export_busiest_days_by_revenue,
    export_busiest_days_by_revenue_csv,
)
from saloncore.models import Salon

DAY = datetime.date(2026, 11, 2)
NEXT = DAY + datetime.timedelta(days=6)


class ExportBusiestRevenueCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")

    def _sale(self, *, salon, price):
        sale = Sale.objects.create(
            salon=salon, status=Sale.Status.COMPLETED
        )
        stamp = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=ZoneInfo("UTC"))
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp
        )
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal(price),
        )
        return sale

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_busiest_revenue", salon_id=self.salon.pk,
            start_date=DAY, end_date=NEXT, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_busiest_days_by_revenue_csv(self.salon, DAY, NEXT))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_busiest_revenue", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", NEXT.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_busiest_days_by_revenue_csv(self.salon, DAY, NEXT))

    def test_salon_scoping(self):
        self._sale(salon=self.salon, price="40.00")
        self._sale(salon=self.other, price="999.00")
        out = io.StringIO()
        call_command(
            "export_busiest_revenue", salon_id=self.salon.pk,
            start_date=DAY, end_date=NEXT, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_busiest_days_by_revenue_csv(self.salon, DAY, NEXT))
        self.assertNotEqual(
            out.getvalue(),
            export_busiest_days_by_revenue_csv(self.other, DAY, NEXT))
        rows = list(csv.DictReader(io.StringIO(out.getvalue())))
        monday = [r for r in rows if r["weekday"] == "0"][0]
        self.assertEqual(monday["revenue"], "40.00")

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "busiest_revenue.csv")
            call_command(
                "export_busiest_revenue", salon_id=self.salon.pk,
                start_date=DAY, end_date=NEXT, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written,
            export_busiest_days_by_revenue_csv(self.salon, DAY, NEXT))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_busiest_revenue", salon_id=self.salon.pk + 999,
                start_date=DAY, end_date=NEXT, stdout=io.StringIO())

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command(
            "export_busiest_revenue", salon_id=self.salon.pk,
            start_date=DAY, end_date=NEXT, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_busiest_days_by_revenue_csv(self.salon, DAY, NEXT))

    def test_explicit_csv_format_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_busiest_revenue", salon_id=self.salon.pk,
            start_date=DAY, end_date=NEXT, format="csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_busiest_days_by_revenue_csv(self.salon, DAY, NEXT))

    def test_csv_flag_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_busiest_revenue", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", NEXT.isoformat(),
            "--format", "csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_busiest_days_by_revenue_csv(self.salon, DAY, NEXT))

    def test_json_output_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command(
            "export_busiest_revenue", salon_id=self.salon.pk,
            start_date=DAY, end_date=NEXT, format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(
            rows, export_busiest_days_by_revenue(self.salon, DAY, NEXT))
        self.assertEqual(
            out.getvalue(),
            json.dumps(export_busiest_days_by_revenue(self.salon, DAY, NEXT),
                       indent=2) + "\n")

    def test_json_flag_matches_dict_service(self):
        out = io.StringIO()
        call_command(
            "export_busiest_revenue", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", NEXT.isoformat(),
            "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_busiest_days_by_revenue(self.salon, DAY, NEXT))

    def test_json_salon_scoping(self):
        self._sale(salon=self.salon, price="40.00")
        self._sale(salon=self.other, price="999.00")
        out = io.StringIO()
        call_command(
            "export_busiest_revenue", salon_id=self.salon.pk,
            start_date=DAY, end_date=NEXT, format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(
            rows, export_busiest_days_by_revenue(self.salon, DAY, NEXT))
        self.assertNotEqual(
            rows, export_busiest_days_by_revenue(self.other, DAY, NEXT))

    def test_json_composes_with_date_window(self):
        out = io.StringIO()
        call_command(
            "export_busiest_revenue", salon_id=self.salon.pk,
            start_date=NEXT, end_date=DAY, format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_busiest_days_by_revenue(self.salon, NEXT, DAY))

    def test_json_output_file_matches_dict_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "busiest_revenue.json")
            call_command(
                "export_busiest_revenue", salon_id=self.salon.pk,
                start_date=DAY, end_date=NEXT, format="json",
                output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written),
            export_busiest_days_by_revenue(self.salon, DAY, NEXT))
        self.assertEqual(out.getvalue(), "")

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_busiest_revenue", salon_id=self.salon.pk,
                start_date=DAY, end_date=NEXT, format="xml",
                stdout=io.StringIO())

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_busiest_revenue", "--salon-id", str(self.salon.pk),
                "--start-date", DAY.isoformat(),
                "--end-date", NEXT.isoformat(), "--format", "xml",
                stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "busiest_revenue.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_busiest_revenue", salon_id=self.salon.pk,
                    start_date=DAY, end_date=NEXT, output=path,
                    stdout=io.StringIO())
