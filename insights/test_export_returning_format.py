import io
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from checkout.models import Sale, SaleItem
from clients.models import Client
from insights.returning_export import (
    RETURNING_FIELDNAMES, export_returning_revenue_csv,
    export_returning_revenue_row,
)
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)

HEADER = ",".join(RETURNING_FIELDNAMES) + "\n"
SEEDED_CSV = HEADER + "2026-11-02,2026-11-08,100.00,60.00,30.00,190.00,2,2,1\n"
SEEDED_ROW = {
    "start_date": "2026-11-02", "end_date": "2026-11-08",
    "returning_revenue": "100.00", "new_revenue": "60.00",
    "unattributed_revenue": "30.00", "total": "190.00",
    "returning_sale_count": 2, "new_sale_count": 2,
    "unattributed_sale_count": 1,
}
ZERO_CSV = HEADER + "2026-11-02,2026-11-08,0.00,0.00,0.00,0.00,0,0,0\n"
ZERO_ROW = {
    "start_date": "2026-11-02", "end_date": "2026-11-08",
    "returning_revenue": "0.00", "new_revenue": "0.00",
    "unattributed_revenue": "0.00", "total": "0.00",
    "returning_sale_count": 0, "new_sale_count": 0,
    "unattributed_sale_count": 0,
}


class ExportReturningFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.returning_client = Client.objects.create(
            salon=self.salon, first_name="Ret", last_name="Urning")
        self.new_client = Client.objects.create(
            salon=self.salon, first_name="New", last_name="Client")

    def _sale(self, client=None, *, day, price="50.00"):
        sale = Sale.objects.create(
            salon=self.salon, client=client, status=Sale.Status.COMPLETED)
        stamp = datetime(2026, 11, 2, 12, 0, tzinfo=UTC) + timedelta(days=day)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal(price))
        return sale

    def _seed(self):
        self._sale(self.returning_client, day=-7, price="999.00")
        self._sale(self.returning_client, day=1, price="85.00")
        self._sale(self.returning_client, day=2, price="15.00")
        self._sale(self.new_client, day=0, price="50.00")
        self._sale(self.new_client, day=3, price="10.00")
        self._sale(None, day=1, price="30.00")

    def test_row_function_and_csv_byte_identical(self):
        self._seed()
        row = export_returning_revenue_row(self.salon, START, END)
        self.assertEqual(row, SEEDED_ROW)
        self.assertEqual(list(row), RETURNING_FIELDNAMES)
        self.assertEqual(export_returning_revenue_csv(self.salon, START, END),
                         SEEDED_CSV)

    def test_default_and_explicit_csv_byte_identical(self):
        self._seed()
        for kwargs in ({}, {"format": "csv"}):
            out = io.StringIO()
            call_command("export_returning", salon_id=self.salon.pk,
                         start_date=START, end_date=END, stdout=out, **kwargs)
            self.assertEqual(out.getvalue(), SEEDED_CSV)

    def test_json_is_one_element_list_exact_serialisation(self):
        self._seed()
        row = export_returning_revenue_row(self.salon, START, END)
        out = io.StringIO()
        call_command("export_returning", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [SEEDED_ROW])
        self.assertEqual(json.loads(out.getvalue()), [row])
        self.assertEqual(out.getvalue(), json.dumps(
            [row], indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_cli_flag(self):
        self._seed()
        out = io.StringIO()
        call_command("export_returning", "--salon-id", str(self.salon.pk),
                     "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [SEEDED_ROW])

    def test_json_output_file(self):
        self._seed()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "returning.json")
            call_command("export_returning", salon_id=self.salon.pk,
                         start_date=START, end_date=END, format="json",
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(json.loads(written), [SEEDED_ROW])
        self.assertEqual(written, json.dumps(
            [SEEDED_ROW], indent=2, cls=DjangoJSONEncoder) + "\n")
        self.assertEqual(out.getvalue(), "")

    def test_zero_case_csv_and_json(self):
        self.assertEqual(export_returning_revenue_row(self.salon, START, END),
                         ZERO_ROW)
        self.assertEqual(export_returning_revenue_csv(self.salon, START, END),
                         ZERO_CSV)
        out = io.StringIO()
        call_command("export_returning", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [ZERO_ROW])

    def test_filter_composition_narrower_window(self):
        self._seed()
        start, end = START, date(2026, 11, 4)
        out = io.StringIO()
        call_command("export_returning", salon_id=self.salon.pk,
                     start_date=start, end_date=end, format="json",
                     stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(rows, [export_returning_revenue_row(
            self.salon, start, end)])
        self.assertEqual(rows, [{
            "start_date": "2026-11-02", "end_date": "2026-11-04",
            "returning_revenue": "100.00", "new_revenue": "50.00",
            "unattributed_revenue": "30.00", "total": "180.00",
            "returning_sale_count": 2, "new_sale_count": 1,
            "unattributed_sale_count": 1,
        }])
        out = io.StringIO()
        call_command("export_returning", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), SEEDED_CSV)

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_returning", salon_id=self.salon.pk,
                         start_date=START, end_date=END, format="xml",
                         stdout=io.StringIO())
