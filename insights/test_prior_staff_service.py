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
from insights.prior_staff_service import (
    PRIOR_SERVICE_FIELDNAMES,
    PRIOR_STAFF_FIELDNAMES,
    export_prior_service_csv,
    export_prior_staff_csv,
    prior_period_service_revenue,
    prior_period_staff_revenue,
)
from insights.service_revenue import revenue_by_service
from insights.staff_revenue import revenue_by_staff
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)
PRIOR_START = date(2026, 10, 26)


class PriorStaffServiceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.alice = StaffMember.objects.create(salon=self.salon, display_name="Alice")
        self.bob = StaffMember.objects.create(salon=self.salon, display_name="Bob")
        self.client = Client.objects.create(salon=self.salon, first_name="Ann", last_name="A")
        self.client_b = Client.objects.create(salon=self.salon, first_name="Ben", last_name="B")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.cut = Service.objects.create(category=cat, name="Haircut", service_minutes=45)
        self.colour = Service.objects.create(category=cat, name="Colour", service_minutes=30)

    def _appt(self, client, staff, day, service=None):
        start = datetime(day.year, day.month, day.day, 10, 0, tzinfo=UTC)
        return Appointment.objects.create(
            client=client, staff_member=staff, service=service or self.cut,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)

    def _sale(self, day, client=None, salon=None):
        sale = Sale.objects.create(salon=salon or self.salon, client=client, status=Sale.Status.COMPLETED)
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(created_at=stamp, completed_at=stamp)
        sale.refresh_from_db()
        return sale

    def _item(self, sale, kind, price, service=None, quantity=1):
        return SaleItem.objects.create(sale=sale, kind=kind, quantity=quantity, unit_price=Decimal(price), service=service)

    def _seed(self):
        # Current: Alice 100 service + 50 product; prior: Alice 50.
        self._appt(self.client, self.alice, date(2026, 11, 5))
        cur = self._sale(date(2026, 11, 5), self.client)
        self._item(cur, SaleItem.Kind.SERVICE, "100.00", self.cut)
        self._item(cur, SaleItem.Kind.PRODUCT, "50.00")
        self._appt(self.client, self.alice, date(2026, 10, 29))
        pri = self._sale(date(2026, 10, 29), self.client)
        self._item(pri, SaleItem.Kind.SERVICE, "50.00", self.cut)

    def test_staff_delta_math_and_bounds(self):
        self._seed()
        r = prior_period_staff_revenue(self.salon, START, END)
        self.assertEqual((r.start_date, r.end_date), (START, END))
        self.assertEqual((r.prior_start_date, r.prior_end_date),
                         (PRIOR_START, date(2026, 11, 1)))
        self.assertEqual(r.days, 7)
        self.assertEqual([x.display_name for x in r], ["Alice"])
        row = r[0]
        self.assertEqual(row.staff, self.alice)
        self.assertEqual((row.total.current, row.total.prior,
                          row.total.delta, row.total.percent_change),
                         (Decimal("150.00"), Decimal("50.00"),
                          Decimal("100.00"), Decimal("200.00")))
        self.assertEqual(row.service.delta, Decimal("50.00"))
        self.assertEqual(row.retail.prior, Decimal("0.00"))
        self.assertIsNone(row.retail.percent_change)
        self.assertEqual((row.current_sale_count, row.prior_sale_count,
                          row.sale_count_delta), (1, 1, 0))
        # Reconciles exactly with the underlying service.
        self.assertEqual(row.total.current,
                         revenue_by_staff(self.salon, START, END)[0].total)

    def test_staff_row_only_in_prior_and_only_in_current(self):
        self._appt(self.client_b, self.bob, date(2026, 10, 28))
        self._item(self._sale(date(2026, 10, 28), self.client_b),
                   SaleItem.Kind.SERVICE, "40.00", self.cut)
        self._seed()
        r = prior_period_staff_revenue(self.salon, START, END)
        by_name = {x.display_name: x for x in r}
        self.assertEqual(by_name["Bob"].total.current, Decimal("0.00"))
        self.assertEqual(by_name["Bob"].total.prior, Decimal("40.00"))
        self.assertEqual(by_name["Bob"].total.percent_change,
                         Decimal("-100.00"))
        self.assertIsNone(by_name["Bob"].current)

    def test_service_delta_math_and_single_period_rows(self):
        self._seed()
        cur2 = self._sale(date(2026, 11, 6))
        self._item(cur2, SaleItem.Kind.SERVICE, "60.00", self.colour)
        r = prior_period_service_revenue(self.salon, START, END)
        by_name = {x.service_name: x for x in r}
        cut = by_name["Haircut"]
        self.assertEqual((cut.revenue.current, cut.revenue.prior,
                          cut.revenue.delta, cut.revenue.percent_change),
                         (Decimal("100.00"), Decimal("50.00"),
                          Decimal("50.00"), Decimal("100.00")))
        self.assertEqual(cut.revenue.current,
                         revenue_by_service(self.salon, START, END)[0].revenue)
        colour = by_name["Colour"]
        self.assertEqual(colour.revenue.prior, Decimal("0.00"))
        self.assertIsNone(colour.revenue.percent_change)
        self.assertIsNone(colour.prior)
        self.assertEqual(colour.current_quantity, 1)

    def _seed_duration(self):
        # Cut (45 min): current qty 2 x 60.00, prior qty 1 x 45.00.
        cur = self._sale(date(2026, 11, 5), self.client)
        self._item(cur, SaleItem.Kind.SERVICE, "60.00", self.cut,
                   quantity=2)
        pri = self._sale(date(2026, 10, 29), self.client)
        self._item(pri, SaleItem.Kind.SERVICE, "45.00", self.cut)
        # Colour (30 min): only in current.
        cur2 = self._sale(date(2026, 11, 6))
        self._item(cur2, SaleItem.Kind.SERVICE, "60.00", self.colour)

    def test_service_duration_and_revenue_per_hour_deltas(self):
        self._seed_duration()
        r = prior_period_service_revenue(self.salon, START, END)
        by_name = {x.service_name: x for x in r}
        cut = by_name["Haircut"]
        # Verbatim from the source rows for both windows.
        src_cur = {x.service_name: x for x in
                   revenue_by_service(self.salon, START, END)}
        src_pri = {x.service_name: x for x in revenue_by_service(
            self.salon, PRIOR_START, date(2026, 11, 1))}
        self.assertEqual(
            cut.total_duration_minutes.current,
            Decimal(src_cur["Haircut"].total_duration_minutes))
        self.assertEqual(
            cut.revenue_per_hour.current,
            src_cur["Haircut"].revenue_per_hour)
        self.assertEqual(
            cut.revenue_per_hour.prior,
            src_pri["Haircut"].revenue_per_hour)
        self.assertEqual(
            (cut.total_duration_minutes.current,
             cut.total_duration_minutes.prior,
             cut.total_duration_minutes.delta,
             cut.total_duration_minutes.percent_change),
            (Decimal("90"), Decimal("45"), Decimal("45"),
             Decimal("100.00")))
        self.assertEqual(
            (cut.revenue_per_hour.current, cut.revenue_per_hour.prior,
             cut.revenue_per_hour.delta,
             cut.revenue_per_hour.percent_change),
            (Decimal("80.00"), Decimal("60.00"), Decimal("20.00"),
             Decimal("33.33")))
        # line_count is a raw pair: 1 line each side, unlike qty 2/1.
        self.assertEqual((cut.current_line_count, cut.prior_line_count,
                          cut.line_count_delta), (1, 1, 0))
        self.assertEqual((cut.current_quantity, cut.prior_quantity),
                         (2, 1))
        self.assertFalse(hasattr(cut, "duration_minutes"))
        colour = by_name["Colour"]
        self.assertEqual(
            (colour.total_duration_minutes.current,
             colour.total_duration_minutes.prior,
             colour.total_duration_minutes.delta),
            (Decimal("30"), Decimal("0"), Decimal("30")))
        self.assertIsNone(
            colour.total_duration_minutes.percent_change)
        # No per-hour figure for a period with no sale: honest None.
        self.assertIsNone(colour.revenue_per_hour)
        self.assertEqual(colour.current.revenue_per_hour,
                         Decimal("120.00"))
        self.assertEqual((colour.current_line_count,
                          colour.prior_line_count), (1, 0))

    def test_service_revenue_per_hour_none_when_duration_unknown(self):
        consult = Service.objects.create(
            category=self.cut.category, name="Consult",
            service_minutes=0)
        self._item(self._sale(date(2026, 11, 5)),
                   SaleItem.Kind.SERVICE, "50.00", consult)
        self._item(self._sale(date(2026, 10, 29)),
                   SaleItem.Kind.SERVICE, "25.00", consult)
        SaleItem.objects.create(
            sale=self._sale(date(2026, 11, 5)),
            kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal("40.00"), description="Mystery")
        SaleItem.objects.create(
            sale=self._sale(date(2026, 10, 29)),
            kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal("20.00"), description="Mystery")
        r = prior_period_service_revenue(self.salon, START, END)
        by_name = {x.service_name: x for x in r}
        for name in ("Consult", "Mystery"):
            row = by_name[name]
            self.assertIsNone(row.current.revenue_per_hour)
            self.assertIsNone(row.prior.revenue_per_hour)
            self.assertIsNone(row.revenue_per_hour)
            self.assertIsNone(row.total_duration_minutes)
            self.assertEqual((row.current_line_count,
                              row.prior_line_count), (1, 1))

    def test_service_csv_duration_and_revenue_per_hour_columns(self):
        self._seed_duration()
        consult = Service.objects.create(
            category=self.cut.category, name="Consult",
            service_minutes=0)
        self._item(self._sale(date(2026, 11, 5)),
                   SaleItem.Kind.SERVICE, "50.00", consult)
        self._item(self._sale(date(2026, 10, 29)),
                   SaleItem.Kind.SERVICE, "25.00", consult)
        text = export_prior_service_csv(self.salon, START, END)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0],
                         PRIOR_SERVICE_FIELDNAMES)
        rows = {x["service_name"]: x
                for x in csv.DictReader(io.StringIO(text))}
        cut = rows["Haircut"]
        self.assertEqual(
            (cut["current_total_duration_minutes"],
             cut["prior_total_duration_minutes"],
             cut["total_duration_minutes_delta"],
             cut["total_duration_minutes_percent_change"]),
            ("90", "45", "45", "100.00"))
        self.assertEqual(
            (cut["current_revenue_per_hour"],
             cut["prior_revenue_per_hour"],
             cut["revenue_per_hour_delta"],
             cut["revenue_per_hour_percent_change"]),
            ("80.00", "60.00", "20.00", "33.33"))
        self.assertEqual((cut["current_line_count"],
                          cut["prior_line_count"]), ("1", "1"))
        colour = rows["Colour"]
        self.assertEqual(
            (colour["current_total_duration_minutes"],
             colour["prior_total_duration_minutes"],
             colour["total_duration_minutes_delta"],
             colour["total_duration_minutes_percent_change"]),
            ("30", "0", "30", ""))
        self.assertEqual(
            (colour["current_revenue_per_hour"],
             colour["prior_revenue_per_hour"],
             colour["revenue_per_hour_delta"],
             colour["revenue_per_hour_percent_change"]),
            ("120.00", "", "", ""))
        consult_row = rows["Consult"]
        self.assertEqual(
            (consult_row["current_total_duration_minutes"],
             consult_row["prior_total_duration_minutes"],
             consult_row["total_duration_minutes_delta"],
             consult_row["current_revenue_per_hour"],
             consult_row["prior_revenue_per_hour"],
             consult_row["revenue_per_hour_delta"]),
            ("", "", "", "", "", ""))
        self.assertEqual((consult_row["current_line_count"],
                          consult_row["prior_line_count"]), ("1", "1"))
        # The export command's service output follows automatically.
        out = io.StringIO()
        call_command("export_prior_staff_service",
                     salon_id=self.salon.pk, kind="service",
                     start_date="2026-11-02", end_date="2026-11-08",
                     stdout=out)
        self.assertIn("current_total_duration_minutes",
                      out.getvalue())
        self.assertIn("revenue_per_hour_delta", out.getvalue())

    def test_zero_prior_percent_none_and_reversed_raises(self):
        self._item(self._sale(date(2026, 11, 5)),
                   SaleItem.Kind.SERVICE, "80.00", self.cut)
        r = prior_period_service_revenue(self.salon, START, END)
        self.assertIsNone(r[0].revenue.percent_change)
        self.assertEqual(prior_period_staff_revenue(
            self.other, START, END), [])
        with self.assertRaises(ValueError):
            prior_period_staff_revenue(self.salon, END, START)
        with self.assertRaises(ValueError):
            prior_period_service_revenue(self.salon, END, START)

    def test_csv_exports_match_services(self):
        self._seed()
        text = export_prior_staff_csv(self.salon, START, END)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0],
                         PRIOR_STAFF_FIELDNAMES)
        self.assertEqual(rows[0]["staff_name"], "Alice")
        self.assertEqual((rows[0]["current"], rows[0]["prior"],
                          rows[0]["delta"], rows[0]["percent_change"]),
                         ("150.00", "50.00", "100.00", "200.00"))
        self.assertEqual(rows[0]["prior_end_date"], "2026-11-01")
        text2 = export_prior_service_csv(self.salon, START, END)
        rows2 = list(csv.DictReader(io.StringIO(text2)))
        self.assertEqual(list(csv.reader(io.StringIO(text2)))[0],
                         PRIOR_SERVICE_FIELDNAMES)
        self.assertEqual(rows2[0]["service_name"], "Haircut")
        self.assertEqual(rows2[0]["percent_change"], "100.00")

    def test_command_exports_and_errors(self):
        self._seed()
        out = io.StringIO()
        call_command("export_prior_staff_service",
                     salon_id=self.salon.pk, kind="service",
                     start_date="2026-11-02", end_date="2026-11-08",
                     stdout=out)
        self.assertIn("Haircut", out.getvalue())
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            call_command("export_prior_staff_service",
                         salon_id=self.salon.pk, kind="staff",
                         start_date="2026-11-02", end_date="2026-11-08",
                         output=path)
            with open(path) as fh:
                self.assertIn("Alice", fh.read())
        with self.assertRaises(CommandError):
            call_command("export_prior_staff_service", salon_id=999999,
                         start_date="2026-11-02", end_date="2026-11-08")
        with self.assertRaises(CommandError):
            call_command("export_prior_staff_service",
                         salon_id=self.salon.pk,
                         start_date="2026-11-08", end_date="2026-11-02")
