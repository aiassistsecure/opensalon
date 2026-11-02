import csv
import io
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.attach_rate import retail_attach_rate
from insights.category_mix import category_mix
from insights.prior_attach_category import (
    PRIOR_ATTACH_FIELDNAMES, PRIOR_CATEGORY_FIELDNAMES,
    export_prior_attach_csv, export_prior_category_mix_csv,
    prior_period_attach_rate, prior_period_category_mix,
)
from saloncore.models import Salon, Service, ServiceCategory

UTC = ZoneInfo("UTC")
START, END = date(2026, 11, 2), date(2026, 11, 8)
CUR, PRI = date(2026, 11, 4), date(2026, 10, 28)
S, P = SaleItem.Kind.SERVICE, SaleItem.Kind.PRODUCT


class PriorAttachCategoryTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        hair = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        nails = ServiceCategory.objects.create(salon=self.salon, name="Nails")
        spa = ServiceCategory.objects.create(salon=self.salon, name="Spa")
        self.cut = Service.objects.create(category=hair, name="Cut", service_minutes=45)
        self.mani = Service.objects.create(category=nails, name="Manicure", service_minutes=30)
        self.facial = Service.objects.create(category=spa, name="Facial", service_minutes=60)

    def _sale(self, day, lines):
        sale = Sale.objects.create(salon=self.salon, status=Sale.Status.COMPLETED)
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(created_at=stamp, completed_at=stamp)
        for kind, price, service in lines:
            SaleItem.objects.create(sale=sale, kind=kind, quantity=1, unit_price=Decimal(price), service=service)
        return sale

    def _seed(self):
        # Current: 3 service sales (Hair 200, Nails 50), 1 attached, retail 50.
        self._sale(CUR, [(S, "100.00", self.cut), (P, "50.00", None)])
        self._sale(CUR, [(S, "100.00", self.cut)])
        self._sale(CUR, [(S, "50.00", self.mani)])
        # Prior: 3 service sales (Hair 200, Spa 40), 1 attached, retail 25.
        self._sale(PRI, [(S, "100.00", self.cut), (P, "25.00", None)])
        self._sale(PRI, [(S, "100.00", self.cut)])
        self._sale(PRI, [(S, "40.00", self.facial)])

    def test_attach_delta_math_and_bounds(self):
        self._seed()
        r = prior_period_attach_rate(self.salon, START, END)
        self.assertEqual((r.start_date, r.end_date), (START, END))
        self.assertEqual((r.prior_start_date, r.prior_end_date),
                         (date(2026, 10, 26), date(2026, 11, 1)))
        self.assertEqual(r.days, 7)
        self.assertEqual((r.service_sales.current, r.service_sales.prior,
                          r.service_sales.delta, r.service_sales.percent_change),
                         (Decimal("3"), Decimal("3"), Decimal("0"), Decimal("0.00")))
        self.assertEqual((r.attach_rate_percent.current, r.attach_rate_percent.prior,
                          r.attach_rate_percent.delta),
                         (Decimal("33.33"), Decimal("33.33"), Decimal("0.00")))
        self.assertEqual((r.retail_revenue.current, r.retail_revenue.prior,
                          r.retail_revenue.delta, r.retail_revenue.percent_change),
                         (Decimal("50.00"), Decimal("25.00"),
                          Decimal("25.00"), Decimal("100.00")))
        self.assertEqual((r.service_revenue.delta, r.service_revenue.percent_change),
                         (Decimal("10.00"), Decimal("4.17")))
        # Reconciles exactly with the underlying service.
        direct = retail_attach_rate(self.salon, days=7, end_date=END)
        self.assertEqual(r.current, direct)
        self.assertEqual(r.current.attach_rate, direct.attach_rate)

    def test_category_delta_and_single_period_rows(self):
        self._seed()
        r = prior_period_category_mix(self.salon, START, END)
        self.assertEqual([x.category_name for x in r], ["Hair", "Nails", "Spa"])
        by_name = {x.category_name: x for x in r}
        hair = by_name["Hair"]
        self.assertEqual((hair.revenue.current, hair.revenue.prior,
                          hair.revenue.delta, hair.revenue.percent_change),
                         (Decimal("200.00"), Decimal("200.00"),
                          Decimal("0.00"), Decimal("0.00")))
        self.assertEqual(hair.revenue.current,
                         category_mix(self.salon, START, END)[0].revenue)
        nails = by_name["Nails"]  # current only: prior zero-filled.
        self.assertEqual(nails.revenue.prior, Decimal("0.00"))
        self.assertIsNone(nails.revenue.percent_change)
        self.assertIsNone(nails.prior)
        self.assertEqual(nails.current_revenue_share_percent, Decimal("20.00"))
        self.assertIsNone(nails.prior_revenue_share_percent)
        spa = by_name["Spa"]  # prior only: current zero-filled.
        self.assertEqual(spa.revenue.current, Decimal("0.00"))
        self.assertEqual(spa.revenue.percent_change, Decimal("-100.00"))
        self.assertIsNone(spa.current)

    def test_zero_prior_percent_none_and_reversed_raises(self):
        self._seed()
        r = prior_period_attach_rate(self.other, START, END)
        self.assertIsNone(r.retail_revenue.percent_change)
        self.assertEqual(r.service_sales.current, Decimal("0"))
        self.assertEqual(prior_period_category_mix(self.other, START, END), [])
        with self.assertRaises(ValueError):
            prior_period_attach_rate(self.salon, END, START)
        with self.assertRaises(ValueError):
            prior_period_category_mix(self.salon, END, START)

    def test_csv_exports_match_services(self):
        self._seed()
        text = export_prior_attach_csv(self.salon, START, END)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0], PRIOR_ATTACH_FIELDNAMES)
        rows = {x["metric"]: x for x in csv.DictReader(io.StringIO(text))}
        self.assertEqual((rows["retail_revenue"]["current"], rows["retail_revenue"]["prior"],
                          rows["retail_revenue"]["delta"], rows["retail_revenue"]["percent_change"]),
                         ("50.00", "25.00", "25.00", "100.00"))
        self.assertEqual(rows["service_sales"]["current"], "3")
        self.assertEqual(rows["attach_rate_percent"]["prior_end_date"], "2026-11-01")
        text2 = export_prior_category_mix_csv(self.salon, START, END)
        self.assertEqual(list(csv.reader(io.StringIO(text2)))[0], PRIOR_CATEGORY_FIELDNAMES)
        rows2 = list(csv.DictReader(io.StringIO(text2)))
        self.assertEqual([x["category_name"] for x in rows2], ["Hair", "Nails", "Spa"])
        self.assertEqual(rows2[1]["percent_change"], "")  # zero prior -> empty
        self.assertEqual(rows2[2]["current"], "0.00")

    def test_command_exports_and_errors(self):
        self._seed()
        out = io.StringIO()
        call_command("export_prior_attach_category", salon_id=self.salon.pk, kind="category_mix",
                     start_date="2026-11-02", end_date="2026-11-08", stdout=out)
        self.assertIn("Hair", out.getvalue())
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            call_command("export_prior_attach_category", salon_id=self.salon.pk, kind="attach",
                         start_date="2026-11-02", end_date="2026-11-08", output=path)
            with open(path) as fh:
                self.assertIn("retail_revenue", fh.read())
        with self.assertRaises(CommandError):
            call_command("export_prior_attach_category", salon_id=999999,
                         start_date="2026-11-02", end_date="2026-11-08")
        with self.assertRaises(CommandError):
            call_command("export_prior_attach_category", salon_id=self.salon.pk,
                         start_date="2026-11-08", end_date="2026-11-02")
