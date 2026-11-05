import io
import json
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.attach_export import (
    ATTACH_RATE_FIELDNAMES, export_attach_rate_csv,
    export_attach_rate_row,
)
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)

HEADER = ",".join(ATTACH_RATE_FIELDNAMES) + "\n"
SEEDED_CSV = (
    HEADER
    + "2026-11-02,2026-11-08,7,4,2,2,1,5,0.5000,50.00,"
      "290.00,45.00,75.00,11.25,22.50,3\n"
)
SEEDED_ROW = {
    "start_date": "2026-11-02", "end_date": "2026-11-08", "days": 7,
    "service_sales": 4, "attached_sales": 2,
    "unattached_service_sales": 2, "product_only_sales": 1,
    "total_completed_sales": 5, "attach_rate": "0.5000",
    "attach_rate_percent": "50.00", "service_revenue": "290.00",
    "retail_revenue": "45.00", "total_retail_revenue": "75.00",
    "retail_revenue_per_service_sale": "11.25",
    "retail_revenue_per_attached_sale": "22.50", "retail_quantity": 3,
}
ZERO_CSV = (
    HEADER
    + "2026-11-02,2026-11-08,7,0,0,0,0,0,0.0000,0.00,"
      "0.00,0.00,0.00,0.00,0.00,0\n"
)
ZERO_ROW = {
    "start_date": "2026-11-02", "end_date": "2026-11-08", "days": 7,
    "service_sales": 0, "attached_sales": 0,
    "unattached_service_sales": 0, "product_only_sales": 0,
    "total_completed_sales": 0, "attach_rate": "0.0000",
    "attach_rate_percent": "0.00", "service_revenue": "0.00",
    "retail_revenue": "0.00", "total_retail_revenue": "0.00",
    "retail_revenue_per_service_sale": "0.00",
    "retail_revenue_per_attached_sale": "0.00", "retail_quantity": 0,
}


class ExportAttachRateFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")

    def _sale(self, day, lines):
        sale = Sale.objects.create(salon=self.salon,
                                   status=Sale.Status.COMPLETED)
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        for kind, price, qty, disc in lines:
            SaleItem.objects.create(
                sale=sale, kind=kind, quantity=qty,
                unit_price=Decimal(price), discount_amount=Decimal(disc))
        return sale

    def _seed(self):
        S, P, R = (SaleItem.Kind.SERVICE, SaleItem.Kind.PRODUCT,
                   SaleItem.Kind.SERIES)
        self._sale(END, [(S, "100.00", 1, "0"), (P, "20.00", 2, "5.00")])
        self._sale(END, [(S, "80.00", 1, "0"), (P, "10.00", 1, "0")])
        self._sale(date(2026, 11, 7), [(S, "60.00", 1, "0")])
        self._sale(date(2026, 11, 7),
                   [(S, "50.00", 1, "0"), (R, "200.00", 1, "0")])
        self._sale(END, [(P, "30.00", 1, "0")])

    def test_row_function_and_csv_byte_identical(self):
        self._seed()
        row = export_attach_rate_row(self.salon, days=7, end_date=END)
        self.assertEqual(row, SEEDED_ROW)
        self.assertEqual(list(row), ATTACH_RATE_FIELDNAMES)
        self.assertEqual(
            export_attach_rate_csv(self.salon, days=7, end_date=END),
            SEEDED_CSV)

    def test_default_and_explicit_csv_byte_identical(self):
        self._seed()
        for kwargs in ({}, {"format": "csv"}):
            out = io.StringIO()
            call_command("export_attach_rate", salon_id=self.salon.pk,
                         start_date=START, end_date=END, stdout=out, **kwargs)
            self.assertEqual(out.getvalue(), SEEDED_CSV)

    def test_json_is_one_element_list_exact_serialisation(self):
        self._seed()
        row = export_attach_rate_row(self.salon, days=7, end_date=END)
        out = io.StringIO()
        call_command("export_attach_rate", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [SEEDED_ROW])
        self.assertEqual(json.loads(out.getvalue()), [row])
        self.assertEqual(out.getvalue(), json.dumps(
            [row], indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_cli_flag(self):
        self._seed()
        out = io.StringIO()
        call_command("export_attach_rate", "--salon-id", str(self.salon.pk),
                     "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [SEEDED_ROW])

    def test_json_output_file(self):
        self._seed()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "attach.json")
            call_command("export_attach_rate", salon_id=self.salon.pk,
                         start_date=START, end_date=END, format="json",
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(json.loads(written), [SEEDED_ROW])
        self.assertEqual(written, json.dumps(
            [SEEDED_ROW], indent=2, cls=DjangoJSONEncoder) + "\n")
        self.assertEqual(out.getvalue(), "")

    def test_zero_case_csv_and_json(self):
        self.assertEqual(
            export_attach_rate_row(self.salon, days=7, end_date=END),
            ZERO_ROW)
        self.assertEqual(
            export_attach_rate_csv(self.salon, days=7, end_date=END),
            ZERO_CSV)
        out = io.StringIO()
        call_command("export_attach_rate", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [ZERO_ROW])

    def test_filter_composition_days_and_window(self):
        self._seed()
        out = io.StringIO()
        call_command("export_attach_rate", salon_id=self.salon.pk,
                     days=3, end_date=END, format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(rows, [export_attach_rate_row(
            self.salon, days=3, end_date=END)])
        self.assertEqual(
            (rows[0]["start_date"], rows[0]["days"]), ("2026-11-06", 3))
        out = io.StringIO()
        call_command("export_attach_rate", salon_id=self.salon.pk,
                     days=7, end_date=END, format="csv", stdout=out)
        self.assertEqual(out.getvalue(), SEEDED_CSV)

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_attach_rate", salon_id=self.salon.pk,
                         start_date=START, end_date=END, format="xml",
                         stdout=io.StringIO())
