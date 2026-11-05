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

from checkout.models import Payment, Refund, Sale, SaleItem
from checkout.refunds import record_refund
from insights.refunds_net_export import (
    REFUNDS_NET_FIELDNAMES, export_refunds_net_csv, export_refunds_net_row,
)
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)

HEADER = ",".join(REFUNDS_NET_FIELDNAMES) + "\n"
SEEDED_CSV = HEADER + "2026-11-02,2026-11-08,7,250.00,35.00,215.00,2\n"
SEEDED_ROW = {
    "start_date": "2026-11-02", "end_date": "2026-11-08", "days": 7,
    "gross_revenue": "250.00", "refund_total": "35.00",
    "net_revenue": "215.00", "refund_count": 2,
}
ZERO_CSV = HEADER + "2026-11-02,2026-11-08,7,0.00,0.00,0.00,0\n"
ZERO_ROW = {
    "start_date": "2026-11-02", "end_date": "2026-11-08", "days": 7,
    "gross_revenue": "0.00", "refund_total": "0.00",
    "net_revenue": "0.00", "refund_count": 0,
}


class ExportRefundsNetFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")

    def _sale(self, day, price="100.00"):
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED)
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal(price))
        Payment.objects.create(
            sale=sale, method=Payment.Method.CASH,
            amount=Decimal(price), status=Payment.Status.COMPLETED)
        sale.refresh_from_db()
        return sale

    def _refund(self, sale, amount, day):
        refund = record_refund(sale, Decimal(amount))
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Refund.objects.filter(pk=refund.pk).update(created_at=stamp)
        return refund

    def _seed(self):
        sale = self._sale(date(2026, 11, 5), "200.00")
        self._sale(date(2026, 11, 6), "50.00")
        self._refund(sale, "20.00", date(2026, 11, 5))
        self._refund(sale, "15.00", date(2026, 11, 7))

    def test_row_function_and_csv_byte_identical(self):
        self._seed()
        row = export_refunds_net_row(self.salon, START, END)
        self.assertEqual(row, SEEDED_ROW)
        self.assertEqual(list(row), REFUNDS_NET_FIELDNAMES)
        self.assertEqual(export_refunds_net_csv(self.salon, START, END),
                         SEEDED_CSV)

    def test_default_and_explicit_csv_byte_identical(self):
        self._seed()
        for kwargs in ({}, {"format": "csv"}):
            out = io.StringIO()
            call_command("export_refunds_net", salon_id=self.salon.pk,
                         start_date=START, end_date=END, stdout=out, **kwargs)
            self.assertEqual(out.getvalue(), SEEDED_CSV)

    def test_json_is_one_element_list_exact_serialisation(self):
        self._seed()
        row = export_refunds_net_row(self.salon, START, END)
        out = io.StringIO()
        call_command("export_refunds_net", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [SEEDED_ROW])
        self.assertEqual(json.loads(out.getvalue()), [row])
        self.assertEqual(out.getvalue(), json.dumps(
            [row], indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_cli_flag(self):
        self._seed()
        out = io.StringIO()
        call_command("export_refunds_net", "--salon-id", str(self.salon.pk),
                     "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [SEEDED_ROW])

    def test_json_output_file(self):
        self._seed()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "refunds_net.json")
            call_command("export_refunds_net", salon_id=self.salon.pk,
                         start_date=START, end_date=END, format="json",
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(json.loads(written), [SEEDED_ROW])
        self.assertEqual(written, json.dumps(
            [SEEDED_ROW], indent=2, cls=DjangoJSONEncoder) + "\n")
        self.assertEqual(out.getvalue(), "")

    def test_zero_case_csv_and_json(self):
        self.assertEqual(export_refunds_net_row(self.salon, START, END),
                         ZERO_ROW)
        self.assertEqual(export_refunds_net_csv(self.salon, START, END),
                         ZERO_CSV)
        out = io.StringIO()
        call_command("export_refunds_net", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [ZERO_ROW])

    def test_filter_composition_narrower_window(self):
        self._seed()
        start, end = date(2026, 11, 6), date(2026, 11, 8)
        out = io.StringIO()
        call_command("export_refunds_net", salon_id=self.salon.pk,
                     start_date=start, end_date=end, format="json",
                     stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(rows, [export_refunds_net_row(self.salon, start, end)])
        self.assertEqual(rows, [{
            "start_date": "2026-11-06", "end_date": "2026-11-08",
            "days": 3, "gross_revenue": "50.00",
            "refund_total": "15.00", "net_revenue": "35.00",
            "refund_count": 1,
        }])
        out = io.StringIO()
        call_command("export_refunds_net", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), SEEDED_CSV)

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_refunds_net", salon_id=self.salon.pk,
                         start_date=START, end_date=END, format="xml",
                         stdout=io.StringIO())
