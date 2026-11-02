import csv
import io
import os
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from checkout.models import Sale, SaleItem
from clients.models import Client
from insights.client_value import client_value
from insights.popularity import service_popularity
from insights.prior_popularity_client_value import (
    PRIOR_CLIENT_VALUE_FIELDNAMES, PRIOR_POPULARITY_FIELDNAMES,
    export_prior_client_value_csv, export_prior_popularity_csv,
    prior_period_client_value, prior_period_popularity,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
START, END = date(2026, 11, 2), date(2026, 11, 8)
PRIOR_START, PRIOR_END = date(2026, 10, 26), date(2026, 11, 1)
CUR, PRI = date(2026, 11, 4), date(2026, 10, 28)


class PriorPopularityClientValueTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.staff = StaffMember.objects.create(salon=self.salon, display_name="Alice")
        self.other_staff = StaffMember.objects.create(salon=self.other, display_name="Oscar")
        self.ann = Client.objects.create(salon=self.salon, first_name="Ann", last_name="A")
        self.ben = Client.objects.create(salon=self.salon, first_name="Ben", last_name="B")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.cut = Service.objects.create(category=cat, name="Haircut", service_minutes=45)
        self.colour = Service.objects.create(category=cat, name="Colour", service_minutes=30)
        self.perm = Service.objects.create(category=cat, name="Perm", service_minutes=60)

    def _appt(self, day, service, status=Appointment.Status.COMPLETED, staff=None):
        start = datetime(day.year, day.month, day.day, 10, 0, tzinfo=UTC)
        return Appointment.objects.create(
            client=self.ann, staff_member=staff or self.staff,
            service=service, start=start, end=start + timedelta(minutes=45),
            status=status)

    def _sale(self, day, client=None, salon=None, price="0.00", service=None):
        sale = Sale.objects.create(salon=salon or self.salon, client=client,
                                   status=Sale.Status.COMPLETED)
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(created_at=stamp, completed_at=stamp)
        if Decimal(price):
            SaleItem.objects.create(sale=sale, kind=SaleItem.Kind.SERVICE,
                                    quantity=1, unit_price=Decimal(price),
                                    service=service)
        return sale

    def _seed_popularity(self):
        self._appt(CUR, self.cut); self._appt(date(2026, 11, 5), self.cut)
        self._appt(CUR, self.cut, Appointment.Status.BOOKED)
        self._appt(CUR, self.colour)
        self._appt(PRI, self.cut)
        self._appt(PRI, self.cut, Appointment.Status.CANCELLED)
        self._appt(PRI, self.perm)
        self._appt(CUR, self.cut, staff=self.other_staff)  # other salon

    def _seed_value(self):
        cur = self._sale(CUR, self.ann)
        SaleItem.objects.create(sale=cur, kind=SaleItem.Kind.SERVICE,
                                quantity=1, unit_price=Decimal("100.00"),
                                service=self.cut)
        SaleItem.objects.create(sale=cur, kind=SaleItem.Kind.SERVICE,
                                quantity=1, unit_price=Decimal("50.00"),
                                service=self.cut)
        self._sale(PRI, self.ann, price="50.00", service=self.cut)
        self._sale(CUR, self.ben, price="60.00", service=self.cut)
        self._sale(CUR, None, price="30.00")  # unattributed
        self._sale(CUR, self.ann, salon=self.other, price="999.00",
                   service=self.cut)  # other salon's book

    def test_popularity_window_math_and_deltas(self):
        self._seed_popularity()
        r = prior_period_popularity(self.salon, START, END)
        self.assertEqual((r.start_date, r.end_date), (START, END))
        self.assertEqual((r.prior_start_date, r.prior_end_date),
                         (PRIOR_START, PRIOR_END))
        self.assertEqual(r.days, 7)
        by_name = {x.service_name: x for x in r}
        self.assertEqual(set(by_name), {"Haircut", "Colour", "Perm"})
        cut = by_name["Haircut"]
        self.assertEqual((cut.total.current, cut.total.prior, cut.total.delta,
                          cut.total.percent_change),
                         (Decimal("3"), Decimal("2"), Decimal("1"),
                          Decimal("50.00")))
        self.assertEqual((cut.completed.current, cut.completed.prior,
                          cut.completed.percent_change),
                         (Decimal("2"), Decimal("1"), Decimal("100.00")))
        self.assertEqual(cut.cancelled_no_show.prior, Decimal("1"))
        svc = {x.service_name: x for x in service_popularity(self.salon, START, END)}
        self.assertEqual(cut.current_total_count, svc["Haircut"].total_count)
        colour = by_name["Colour"]  # current only
        self.assertIsNone(colour.prior)
        self.assertEqual(colour.total.prior, Decimal("0"))
        self.assertIsNone(colour.total.percent_change)
        perm = by_name["Perm"]  # prior only
        self.assertIsNone(perm.current)
        self.assertEqual(perm.total.current, Decimal("0"))
        self.assertEqual(perm.total.percent_change, Decimal("-100.00"))

    def test_client_value_deltas_unattributed_and_scoping(self):
        self._seed_value()
        r = prior_period_client_value(self.salon, START, END)
        self.assertEqual((r.prior_start_date, r.prior_end_date),
                         (PRIOR_START, PRIOR_END))
        by_name = {x.display_name: x for x in r}
        self.assertEqual(set(by_name), {"Ann A", "Ben B"})
        ann = by_name["Ann A"]
        self.assertEqual((ann.revenue.current, ann.revenue.prior,
                          ann.revenue.delta, ann.revenue.percent_change),
                         (Decimal("150.00"), Decimal("50.00"),
                          Decimal("100.00"), Decimal("200.00")))
        self.assertEqual((ann.current_sale_count, ann.prior_sale_count,
                          ann.sale_count_delta), (1, 1, 0))
        self.assertIsNone(by_name["Ben B"].prior)
        self.assertIsNone(by_name["Ben B"].revenue.percent_change)
        self.assertEqual((r.unattributed.current, r.unattributed.prior,
                          r.unattributed.delta),
                         (Decimal("30.00"), Decimal("0.00"),
                          Decimal("30.00")))
        self.assertIsNone(r.unattributed.percent_change)
        self.assertEqual(r.unattributed_current_sale_count, 1)
        self.assertEqual(ann.revenue.current,
                         client_value(self.salon, START, END).rows[0].total)

    def test_reversed_window_raises_and_empty_salon(self):
        with self.assertRaises(ValueError):
            prior_period_popularity(self.salon, END, START)
        with self.assertRaises(ValueError):
            prior_period_client_value(self.salon, END, START)
        self.assertEqual(prior_period_popularity(self.other, START, END), [])
        empty = prior_period_client_value(self.other, START, END)
        self.assertEqual(list(empty), [])
        self.assertEqual(empty.unattributed.current, Decimal("0.00"))

    def test_csv_exports_agree_with_comparisons(self):
        self._seed_popularity(); self._seed_value()
        text = export_prior_popularity_csv(self.salon, START, END)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0],
                         PRIOR_POPULARITY_FIELDNAMES)
        by_name = {x["service_name"]: x for x in rows}
        self.assertEqual((by_name["Haircut"]["current"], by_name["Haircut"]["prior"],
                          by_name["Haircut"]["delta"],
                          by_name["Haircut"]["percent_change"]),
                         ("3", "2", "1", "50.00"))
        self.assertEqual(by_name["Colour"]["percent_change"], "")
        self.assertEqual(by_name["Haircut"]["prior_end_date"], "2026-11-01")
        comp = {x.service_name: x for x in
                prior_period_popularity(self.salon, START, END)}
        for name, row in by_name.items():
            self.assertEqual(int(row["current"]), comp[name].current_total_count)
            self.assertEqual(int(row["prior"]), comp[name].prior_total_count)
        text2 = export_prior_client_value_csv(self.salon, START, END)
        rows2 = list(csv.DictReader(io.StringIO(text2)))
        self.assertEqual(list(csv.reader(io.StringIO(text2)))[0],
                         PRIOR_CLIENT_VALUE_FIELDNAMES)
        by_client = {x["client_name"]: x for x in rows2}
        self.assertEqual((by_client["Ann A"]["current"], by_client["Ann A"]["prior"],
                          by_client["Ann A"]["percent_change"]),
                         ("150.00", "50.00", "200.00"))
        self.assertEqual(by_client["Ben B"]["percent_change"], "")

    def test_command_exports_and_errors(self):
        self._seed_popularity(); self._seed_value()
        out = io.StringIO()
        call_command("export_prior_popularity_client_value",
                     salon_id=self.salon.pk, kind="popularity",
                     start_date="2026-11-02", end_date="2026-11-08", stdout=out)
        self.assertIn("Haircut", out.getvalue())
        with self.assertRaises(CommandError):
            call_command("export_prior_popularity_client_value", salon_id=999999,
                         start_date="2026-11-02", end_date="2026-11-08")
        with self.assertRaises(CommandError):
            call_command("export_prior_popularity_client_value",
                         salon_id=self.salon.pk, start_date="2026-11-08",
                         end_date="2026-11-02")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            call_command("export_prior_popularity_client_value",
                         salon_id=self.salon.pk, kind="client_value",
                         start_date="2026-11-02", end_date="2026-11-08",
                         output=path)
            with open(path) as fh:
                self.assertIn("Ann A", fh.read())
