import csv
import io
import os
import tempfile
from datetime import date, datetime, timedelta
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

    def test_attach_daily_offset_aligned_and_verbatim(self):
        self._seed()
        r = prior_period_attach_rate(self.salon, START, END)
        self.assertEqual(len(r.daily), 7)
        self.assertEqual(r.per_day, r.daily)
        self.assertEqual(r.by_day, r.daily)
        self.assertEqual([d.offset for d in r.daily], list(range(7)))
        self.assertEqual(set(r.by_offset), set(range(7)))
        # Verbatim from the source's own daily series, both windows.
        direct = retail_attach_rate(self.salon, days=7, end_date=END)
        prior_direct = retail_attach_rate(
            self.salon, days=7, end_date=date(2026, 11, 1))
        self.assertEqual([d.current for d in r.daily],
                         list(direct.daily))
        self.assertEqual([d.prior for d in r.daily],
                         list(prior_direct.daily))
        day0, day2 = r.by_offset[0], r.by_offset[2]
        self.assertEqual((day0.current_date, day0.prior_date),
                         (START, date(2026, 10, 26)))
        self.assertEqual((day2.date, day2.current_date, day2.prior_date),
                         (CUR, CUR, PRI))
        # Seeded sales all land on offset 2 in both windows.
        for comp, want in (
            (day2.service_sales, ("3", "3", "0", "0.00")),
            (day2.attached_sales, ("1", "1", "0", "0.00")),
            (day2.retail_revenue, ("50.00", "25.00", "25.00", "100.00")),
            (day2.service_revenue, ("250.00", "240.00", "10.00", "4.17")),
        ):
            self.assertEqual(
                (comp.current, comp.prior, comp.delta,
                 comp.percent_change),
                tuple(Decimal(v) for v in want))
        self.assertEqual(set(day2.deltas), {
            "service_sales", "attached_sales", "retail_revenue",
            "service_revenue"})
        # attach_rate follows from the compared counts on the days.
        self.assertEqual(day2.current_attach_rate, Decimal("0.3333"))
        self.assertEqual(day2.prior_attach_rate, Decimal("0.3333"))
        self.assertEqual(day2.current.attach_rate,
                         day2.current_attach_rate)
        # Zero-filled day: figures zero, percent None (prior zero).
        self.assertEqual(
            (day0.service_sales.current, day0.service_sales.prior,
             day0.service_sales.delta), (Decimal("0"),) * 3)
        self.assertIsNone(day0.retail_revenue.percent_change)
        # Daily deltas reconcile with the window totals.
        for name in ("service_sales", "attached_sales"):
            self.assertEqual(
                sum(getattr(d, name).current for d in r.daily),
                getattr(r, name).current)
            self.assertEqual(
                sum(getattr(d, name).prior for d in r.daily),
                getattr(r, name).prior)
        for name in ("retail_revenue", "service_revenue"):
            self.assertEqual(
                sum((getattr(d, name).current for d in r.daily),
                    Decimal("0.00")), getattr(r, name).current)

    def test_attach_daily_zero_filled_for_empty_salon(self):
        r = prior_period_attach_rate(self.other, START, END)
        self.assertEqual(len(r.daily), 7)
        self.assertEqual([d.current_date for d in r.daily],
                         [START + timedelta(days=i) for i in range(7)])
        self.assertEqual([d.prior_date for d in r.daily],
                         [date(2026, 10, 26) + timedelta(days=i)
                          for i in range(7)])
        self.assertTrue(all(
            (d.service_sales.current, d.attached_sales.prior,
             d.retail_revenue.delta, d.service_revenue.delta)
            == (Decimal("0"), Decimal("0"), Decimal("0.00"),
                Decimal("0.00"))
            and d.service_sales.percent_change is None
            for d in r.daily))

    def test_attach_daily_csv_rows_and_command(self):
        self._seed()
        text = export_prior_attach_csv(self.salon, START, END)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0],
                         PRIOR_ATTACH_FIELDNAMES)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 10 + 7 * 4)
        summary, daily = rows[:10], rows[10:]
        self.assertTrue(all(
            (x["offset"], x["current_date"], x["prior_date"])
            == ("", "", "") for x in summary))
        self.assertEqual([x["metric"] for x in daily],
                         [f"daily_{n}" for _ in range(7) for n in (
                             "service_sales", "attached_sales",
                             "retail_revenue", "service_revenue")])
        by_key = {(x["metric"], x["offset"]): x for x in daily}
        svc = by_key[("daily_service_sales", "2")]
        self.assertEqual(
            (svc["current"], svc["prior"], svc["delta"],
             svc["percent_change"], svc["current_date"],
             svc["prior_date"]),
            ("3", "3", "0", "0.00", "2026-11-04", "2026-10-28"))
        ret = by_key[("daily_retail_revenue", "2")]
        self.assertEqual(
            (ret["current"], ret["prior"], ret["delta"],
             ret["percent_change"]), ("50.00", "25.00", "25.00",
                                       "100.00"))
        self.assertEqual(
            by_key[("daily_service_revenue", "0")][
                "percent_change"], "")  # zero prior -> empty
        out = io.StringIO()
        call_command("export_prior_attach_category",
                     salon_id=self.salon.pk, kind="attach",
                     start_date="2026-11-02", end_date="2026-11-08",
                     stdout=out)
        self.assertIn("daily_retail_revenue", out.getvalue())
        self.assertIn("2026-10-28", out.getvalue())

    def test_attach_missing_metrics_deltas_and_csv(self):
        self._seed()
        # Current extras: product-only, attached, unattached sales.
        self._sale(CUR, [(P, "30.00", None)])
        self._sale(CUR, [(S, "60.00", self.cut), (P, "20.00", None)])
        self._sale(CUR, [(S, "80.00", self.cut)])
        # Prior extras: two product-only sales.
        self._sale(PRI, [(P, "10.00", None)])
        self._sale(PRI, [(P, "15.00", None)])
        r = prior_period_attach_rate(self.salon, START, END)
        self.assertEqual(
            (r.unattached_service_sales.current,
             r.unattached_service_sales.prior,
             r.unattached_service_sales.delta,
             r.unattached_service_sales.percent_change),
            (Decimal("3"), Decimal("2"), Decimal("1"),
             Decimal("50.00")))
        self.assertEqual(
            (r.product_only_sales.current, r.product_only_sales.prior,
             r.product_only_sales.delta,
             r.product_only_sales.percent_change),
            (Decimal("1"), Decimal("2"), Decimal("-1"),
             Decimal("-50.00")))
        self.assertEqual(
            (r.total_completed_sales.current,
             r.total_completed_sales.prior,
             r.total_completed_sales.delta,
             r.total_completed_sales.percent_change),
            (Decimal("6"), Decimal("5"), Decimal("1"),
             Decimal("20.00")))
        self.assertEqual(
            (r.retail_quantity.current, r.retail_quantity.prior,
             r.retail_quantity.delta, r.retail_quantity.percent_change),
            (Decimal("2"), Decimal("1"), Decimal("1"),
             Decimal("100.00")))
        # Verbatim from the source service for both windows.
        direct = retail_attach_rate(self.salon, days=7, end_date=END)
        prior_direct = retail_attach_rate(
            self.salon, days=7, end_date=date(2026, 11, 1))
        for name in ("unattached_service_sales", "product_only_sales",
                     "total_completed_sales", "retail_quantity"):
            self.assertEqual(getattr(r, name).current,
                             Decimal(getattr(direct, name)))
            self.assertEqual(getattr(r, name).prior,
                             Decimal(getattr(prior_direct, name)))
        text = export_prior_attach_csv(self.salon, START, END)
        rows = {x["metric"]: x for x in csv.DictReader(io.StringIO(text))}
        # 10 summary metrics + 4 distinct daily_<metric> names.
        self.assertEqual(len(rows), 14)
        self.assertEqual(
            (rows["unattached_service_sales"]["current"],
             rows["unattached_service_sales"]["prior"],
             rows["unattached_service_sales"]["delta"],
             rows["unattached_service_sales"]["percent_change"]),
            ("3", "2", "1", "50.00"))
        self.assertEqual(
            (rows["product_only_sales"]["current"],
             rows["product_only_sales"]["delta"]), ("1", "-1"))
        self.assertEqual(rows["total_completed_sales"]["current"], "6")
        self.assertEqual(rows["retail_quantity"]["current"], "2")
        out = io.StringIO()
        call_command("export_prior_attach_category",
                     salon_id=self.salon.pk, kind="attach",
                     start_date="2026-11-02", end_date="2026-11-08",
                     stdout=out)
        self.assertIn("retail_quantity", out.getvalue())
        self.assertIn("product_only_sales", out.getvalue())

    def test_attach_retail_quantity_counts_units_not_lines(self):
        sale = self._sale(CUR, [(S, "100.00", self.cut),
                                (P, "10.00", None)])
        SaleItem.objects.filter(sale=sale, kind=P).update(quantity=3)
        self._sale(PRI, [(S, "100.00", self.cut), (P, "10.00", None)])
        r = prior_period_attach_rate(self.salon, START, END)
        self.assertEqual(
            (r.retail_quantity.current, r.retail_quantity.prior,
             r.retail_quantity.delta, r.retail_quantity.percent_change),
            (Decimal("3"), Decimal("1"), Decimal("2"),
             Decimal("200.00")))

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
