import csv
import io
import os
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase

from checkout.models import Payment, Refund, Sale, SaleItem
from checkout.refunds import record_refund
from insights.prior_refunds_net import prior_refunds_net
from insights.prior_refunds_net_export import (
    PRIOR_REFUNDS_NET_FIELDNAMES,
    export_prior_refunds_net_csv,
)
from insights.refunds_net import refunds_net_revenue
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)
PRIOR_START = START - timedelta(days=7)
PRIOR_END = START - timedelta(days=1)


class PriorRefundsNetTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        # Prior window: gross 100, refunds 20, net 80, 1 refund.
        prior_sale = self._sale(date(2026, 10, 28), "100.00")
        self._refund(prior_sale, "20.00", date(2026, 10, 29))
        # Current window: gross 200, refunds 10, net 190, 1 refund.
        current_sale = self._sale(date(2026, 11, 5), "200.00")
        self._refund(current_sale, "10.00", date(2026, 11, 6))

    def _sale(self, day, price):
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

    def test_both_windows_verbatim_vs_source(self):
        r = prior_refunds_net(self.salon, START, END)
        self.assertEqual(
            r.current, refunds_net_revenue(self.salon, START, END))
        self.assertEqual(
            r.prior,
            refunds_net_revenue(self.salon, PRIOR_START, PRIOR_END))
        self.assertEqual((r.prior_start_date, r.prior_end_date),
                         (PRIOR_START, PRIOR_END))
        self.assertEqual((r.start_date, r.end_date, r.days), (START, END, 7))
        self.assertEqual(r.previous, r.prior)

    def test_delta_and_percent_change(self):
        r = prior_refunds_net(self.salon, START, END)
        self.assertEqual(
            (r.gross.current, r.gross.prior, r.gross.delta,
             r.gross.percent_change),
            (Decimal("200.00"), Decimal("100.00"), Decimal("100.00"),
             Decimal("100.00")))
        self.assertEqual(
            (r.refunds.current, r.refunds.prior, r.refunds.delta,
             r.refunds.percent_change),
            (Decimal("10.00"), Decimal("20.00"), Decimal("-10.00"),
             Decimal("-50.00")))
        self.assertEqual(
            (r.net.current, r.net.prior, r.net.delta,
             r.net.percent_change),
            (Decimal("190.00"), Decimal("80.00"), Decimal("110.00"),
             Decimal("137.50")))
        self.assertEqual(
            (r.refund_count.current, r.refund_count.prior,
             r.refund_count.delta, r.refund_count.percent_change),
            (Decimal("1"), Decimal("1"), Decimal("0"),
             Decimal("0.00")))
        for comp in (r.gross, r.refunds, r.net, r.refund_count):
            self.assertIsInstance(comp.current, Decimal)
            self.assertIsInstance(comp.prior, Decimal)
            self.assertIsInstance(comp.delta, Decimal)

    def test_percent_change_none_when_prior_zero(self):
        other = Salon.objects.create(name="Fresh", timezone="UTC")
        sale = Sale.objects.create(
            salon=other, status=Sale.Status.COMPLETED)
        stamp = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal("50.00"))
        r = prior_refunds_net(other, START, END)
        self.assertEqual(r.prior.net, Decimal("0.00"))
        for comp in (r.gross, r.refunds, r.net, r.refund_count):
            self.assertIsNone(comp.percent_change)
            self.assertEqual(comp.delta, comp.current)

    def test_reversed_window_raises(self):
        with self.assertRaises(ValueError):
            prior_refunds_net(self.salon, END, START)
        with self.assertRaises(ValueError):
            export_prior_refunds_net_csv(self.salon, END, START)


class PriorRefundsNetExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")

    def test_csv_shape_and_values_match_service(self):
        text = export_prior_refunds_net_csv(self.salon, START, END)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], PRIOR_REFUNDS_NET_FIELDNAMES)
        self.assertEqual([row[0] for row in rows[1:]],
                         ["gross", "refunds", "net", "refund_count"])
        result = prior_refunds_net(self.salon, START, END)
        by_metric = {row["metric"]: row
                     for row in csv.DictReader(io.StringIO(text))}
        for name in ("gross", "refunds", "net"):
            comp = getattr(result, name)
            self.assertEqual(Decimal(by_metric[name]["current"]),
                             comp.current)
            self.assertEqual(Decimal(by_metric[name]["prior"]), comp.prior)
            self.assertEqual(Decimal(by_metric[name]["delta"]), comp.delta)
        count_row = by_metric["refund_count"]
        self.assertEqual(count_row["current"], "0")
        self.assertEqual(count_row["percent_change"], "")
        self.assertEqual(by_metric["gross"]["current_start_date"],
                         START.isoformat())
        self.assertEqual(by_metric["gross"]["prior_start_date"],
                         PRIOR_START.isoformat())
        self.assertEqual(by_metric["gross"]["prior_end_date"],
                         PRIOR_END.isoformat())


class ExportPriorRefundsNetCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Example Salon", timezone="UTC")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_refunds_net", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_refunds_net_csv(self.salon, START, END))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command("export_prior_refunds_net",
                     "--salon-id", str(self.salon.pk),
                     "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_refunds_net_csv(self.salon, START, END))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_refunds_net.csv")
            call_command("export_prior_refunds_net",
                         salon_id=self.salon.pk, start_date=START,
                         end_date=END, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written,
            export_prior_refunds_net_csv(self.salon, START, END))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_refunds_net",
                         salon_id=self.salon.pk + 999,
                         start_date=START, end_date=END,
                         stdout=io.StringIO())

    def test_missing_and_invalid_dates_raise_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_refunds_net",
                         salon_id=self.salon.pk, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_refunds_net",
                         salon_id=self.salon.pk, start_date="not-a-date",
                         end_date=END, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_refunds_net", "--salon-id",
                         str(self.salon.pk), "--start-date", "2026-13-40",
                         "--end-date", END.isoformat(), stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_refunds_net",
                         salon_id=self.salon.pk, start_date=END,
                         end_date=START, stdout=io.StringIO())
