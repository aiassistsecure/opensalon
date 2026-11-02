import csv
import io
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from checkout.models import Sale, SaleItem
from clients.models import Client
from insights.prior_retention_returning import (
    prior_period_retention, prior_period_returning_revenue)
from insights.prior_retention_returning_export import (
    PRIOR_RETENTION_FIELDNAMES, PRIOR_RETURNING_FIELDNAMES,
    export_prior_retention_csv, export_prior_returning_csv)
from insights.retention import repeat_visit_retention
from insights.returning import new_vs_returning_revenue
from saloncore.models import Salon
from team.models import StaffMember

UTC = ZoneInfo("UTC")
START, END = date(2026, 11, 2), date(2026, 11, 8)
PRIOR_START, PRIOR_END = date(2026, 10, 26), date(2026, 11, 1)


class PriorRetentionReturningTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.staff = StaffMember.objects.create(salon=self.salon, display_name="Alice")
        self.clients = {n: Client.objects.create(salon=self.salon, first_name=n, last_name="T")
                        for n in ("A", "B", "C", "D", "Ret", "NewP", "NewC")}

    def _appt(self, client, day):
        start = datetime(day.year, day.month, day.day, 10, 0, tzinfo=UTC)
        return Appointment.objects.create(
            client=client, staff_member=self.staff, start=start,
            end=start + timedelta(minutes=45), status=Appointment.Status.COMPLETED)

    def _sale(self, day, client=None, price="0.00"):
        sale = Sale.objects.create(salon=self.salon, client=client, status=Sale.Status.COMPLETED)
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(created_at=stamp, completed_at=stamp)
        if Decimal(price):
            SaleItem.objects.create(sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1, unit_price=Decimal(price))
        return sale

    def _seed_retention(self):
        # Current A,B x2 visits: active 2, repeat 2, total 4, rate 1.0, avg 2.0.
        # Prior A,B,C,D x1: active 4, repeat 0, total 4, rate 0.0, avg 1.0.
        for n, days in (("A", (2, 4)), ("B", (3, 5))):
            for d in days:
                self._appt(self.clients[n], date(2026, 11, d))
        for n in ("A", "B", "C", "D"):
            self._appt(self.clients[n], date(2026, 10, 28))

    def _seed_returning(self):
        self._sale(date(2026, 10, 20), self.clients["Ret"], "999.00")
        self._sale(date(2026, 10, 28), self.clients["Ret"], "100.00")
        self._sale(date(2026, 11, 4), self.clients["Ret"], "150.00")
        self._sale(date(2026, 10, 28), self.clients["NewP"], "50.00")
        self._sale(date(2026, 11, 4), self.clients["NewC"], "60.00")
        self._sale(date(2026, 11, 3), None, "30.00")
        self._sale(date(2026, 10, 27), None, "10.00")

    def test_retention_both_windows_and_deltas(self):
        self._seed_retention()
        r = prior_period_retention(self.salon, START, END)
        self.assertEqual((r.start_date, r.end_date), (START, END))
        self.assertEqual((r.prior_start_date, r.prior_end_date), (PRIOR_START, PRIOR_END))
        self.assertEqual(r.days, 7)
        self.assertEqual((r.active_clients.current, r.active_clients.prior,
                          r.active_clients.delta, r.active_clients.percent_change),
                         (Decimal("2"), Decimal("4"), Decimal("-2"), Decimal("-50.00")))
        self.assertEqual((r.total_visits.current, r.total_visits.delta,
                          r.total_visits.percent_change),
                         (Decimal("4"), Decimal("0"), Decimal("0.00")))
        self.assertIsNone(r.repeat_clients.percent_change)  # zero prior
        self.assertIsNone(r.repeat_rate.percent_change)
        self.assertEqual((r.repeat_rate.current, r.repeat_rate.delta), (Decimal("1.0"), Decimal("1.0")))
        self.assertEqual((r.average_visits_per_active_client.current,
                          r.average_visits_per_active_client.prior,
                          r.average_visits_per_active_client.percent_change),
                         (Decimal("2.0"), Decimal("1.0"), Decimal("100.00")))
        self.assertEqual(r.current, repeat_visit_retention(self.salon, START, END))
        self.assertEqual(r.prior, repeat_visit_retention(self.salon, PRIOR_START, PRIOR_END))

    def test_returning_both_windows_and_deltas(self):
        self._seed_returning()
        r = prior_period_returning_revenue(self.salon, START, END)
        self.assertEqual((r.prior_start_date, r.prior_end_date), (PRIOR_START, PRIOR_END))
        self.assertEqual((r.returning_revenue.current, r.returning_revenue.prior,
                          r.returning_revenue.delta, r.returning_revenue.percent_change),
                         (Decimal("150.00"), Decimal("100.00"), Decimal("50.00"), Decimal("50.00")))
        self.assertEqual((r.new_revenue.current, r.new_revenue.prior, r.new_revenue.percent_change),
                         (Decimal("60.00"), Decimal("50.00"), Decimal("20.00")))
        self.assertEqual((r.unattributed_revenue.current, r.unattributed_revenue.percent_change),
                         (Decimal("30.00"), Decimal("200.00")))
        self.assertEqual((r.total.current, r.total.prior, r.total.delta),
                         (Decimal("240.00"), Decimal("160.00"), Decimal("80.00")))
        self.assertEqual((r.total_sale_count.current, r.total_sale_count.prior,
                          r.total_sale_count.percent_change),
                         (Decimal("3"), Decimal("3"), Decimal("0.00")))
        self.assertEqual(r.current, new_vs_returning_revenue(self.salon, START, END))
        self.assertEqual(r.prior, new_vs_returning_revenue(self.salon, PRIOR_START, PRIOR_END))

    def test_reversed_raises_and_empty_zero_prior(self):
        for fn in (prior_period_retention, prior_period_returning_revenue):
            with self.assertRaises(ValueError):
                fn(self.salon, END, START)
        empty = prior_period_retention(self.other, START, END)
        self.assertEqual(empty.active_clients.current, Decimal("0"))
        self.assertIsNone(empty.active_clients.percent_change)
        empty2 = prior_period_returning_revenue(self.other, START, END)
        self.assertEqual(empty2.total.current, Decimal("0.00"))
        self.assertIsNone(empty2.total.percent_change)

    def test_csv_shape_and_values(self):
        self._seed_retention(); self._seed_returning()
        text = export_prior_retention_csv(self.salon, START, END)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0], PRIOR_RETENTION_FIELDNAMES)
        self.assertEqual([x["metric"] for x in rows],
                         ["active_clients", "repeat_clients", "total_visits",
                          "repeat_rate", "average_visits_per_active_client"])
        by = {x["metric"]: x for x in rows}
        self.assertEqual((by["active_clients"]["current"], by["active_clients"]["prior"],
                          by["active_clients"]["percent_change"]), ("2", "4", "-50.00"))
        self.assertEqual(by["repeat_clients"]["percent_change"], "")
        self.assertEqual(by["repeat_rate"]["current"], "1.0000")
        self.assertEqual(by["active_clients"]["prior_end_date"], "2026-11-01")
        text2 = export_prior_returning_csv(self.salon, START, END)
        rows2 = list(csv.DictReader(io.StringIO(text2)))
        self.assertEqual(list(csv.reader(io.StringIO(text2)))[0], PRIOR_RETURNING_FIELDNAMES)
        self.assertEqual(len(rows2), 8)
        by2 = {x["metric"]: x for x in rows2}
        self.assertEqual((by2["total"]["current"], by2["total"]["prior"],
                          by2["total"]["delta"], by2["total"]["percent_change"]),
                         ("240.00", "160.00", "80.00", "50.00"))
        self.assertEqual(by2["total_sale_count"]["current"], "3")

    def test_command_stdout_file_and_errors(self):
        self._seed_retention(); self._seed_returning()
        out = io.StringIO()
        call_command("export_prior_retention_returning", salon_id=self.salon.pk,
                     kind="retention", start_date="2026-11-02", end_date="2026-11-08", stdout=out)
        self.assertIn("active_clients", out.getvalue())
        out2 = io.StringIO()
        call_command("export_prior_retention_returning", salon_id=self.salon.pk,
                     kind="returning", start_date="2026-11-02", end_date="2026-11-08", stdout=out2)
        self.assertIn("returning_revenue", out2.getvalue())
        with self.assertRaises(CommandError):
            call_command("export_prior_retention_returning", salon_id=999999,
                         start_date="2026-11-02", end_date="2026-11-08")
        with self.assertRaises(CommandError):
            call_command("export_prior_retention_returning", salon_id=self.salon.pk,
                         start_date="2026-11-08", end_date="2026-11-02")
        with self.assertRaises(CommandError):
            call_command("export_prior_retention_returning", salon_id=self.salon.pk,
                         start_date="not-a-date", end_date="2026-11-08")
        # __file__-anchored path: tempfile is broken on this box (/tmp collisions).
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prior_retention_returning_out.csv")
        try:
            call_command("export_prior_retention_returning", salon_id=self.salon.pk,
                         kind="returning", start_date="2026-11-02", end_date="2026-11-08", output=path)
            with open(path) as fh:
                self.assertIn("240.00", fh.read())
        finally:
            if os.path.exists(path):
                os.remove(path)
