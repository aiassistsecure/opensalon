import csv, io, os, tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from checkout.models import Sale, SaleItem
from clients.models import Client
from insights.prior_busiest import prior_busiest
from insights.prior_busiest_export import (
    PRIOR_BUSIEST_FIELDNAMES, export_prior_busiest, export_prior_busiest_csv)
from insights.services import busiest_days
from saloncore.models import Salon, Service, ServiceCategory, ServicePrice, StaffLevel
from team.models import StaffMember

UTC = ZoneInfo("UTC")
START, END = date(2026, 11, 2), date(2026, 11, 8)  # Monday..Sunday
PRIOR_START, PRIOR_END = START - timedelta(days=7), START - timedelta(days=1)


class _Base(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        level = StaffLevel.objects.create(salon=self.salon, name="L1")
        other_level = StaffLevel.objects.create(salon=self.other, name="L1")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="One", staff_level=level)
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other", staff_level=other_level)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        ServicePrice.objects.create(service=self.service, staff_level=level,
                                    amount=Decimal("85.00"))
        # Prior Mon 1 appt/$50 vs current Mon 2/$100.
        self._appt(date(2026, 10, 26)); self._sale(date(2026, 10, 26), "50.00")
        self._appt(START); self._appt(START, hour=14); self._sale(START, "100.00")
        # Prior Sat 3 appts/$30 vs current Sat 1/$60: rank order differs
        # between windows, so rank-keying would mismatch these rows.
        for hour in (9, 12, 15): self._appt(date(2026, 10, 31), hour=hour)
        self._sale(date(2026, 10, 31), "30.00")
        self._appt(date(2026, 11, 7)); self._sale(date(2026, 11, 7), "60.00")
        self._appt(date(2026, 11, 4))  # current Wed only: prior-zero

    def _appt(self, day, hour=10, staff=None):
        start = datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.staff,
            service=self.service, start=start,
            end=start + timedelta(minutes=45), status=Appointment.Status.BOOKED)

    def _sale(self, day, price, salon=None):
        sale = Sale.objects.create(salon=salon or self.salon,
                                   status=Sale.Status.COMPLETED)
        stamp = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
                                unit_price=Decimal(price))
        return sale


class PriorBusiestTests(_Base):
    def test_both_windows_verbatim_and_bounds(self):
        r = prior_busiest(self.salon, START, END)
        self.assertEqual(list(r.current), busiest_days(self.salon, START, END))
        self.assertEqual(list(r.prior), busiest_days(self.salon, PRIOR_START, PRIOR_END))
        self.assertEqual((r.start_date, r.end_date, r.days), (START, END, 7))
        self.assertEqual((r.prior_start_date, r.prior_end_date), (PRIOR_START, PRIOR_END))
        self.assertEqual(r.previous, r.prior)
        self.assertEqual([row.weekday for row in r.weekdays], list(range(7)))
        self.assertEqual(set(r.by_weekday), set(range(7)))

    def test_weekday_keying_delta_and_percent(self):
        r = prior_busiest(self.salon, START, END)
        mon, sat = r.by_weekday[0], r.by_weekday[5]
        self.assertEqual((mon.weekday_name, sat.weekday_name), ("Monday", "Saturday"))
        for comp, want in (
            (mon.count, (2, 1, 1, "100.00")),
            (mon.appointment_value, ("170.00", "85.00", "85.00", "100.00")),
            (mon.revenue, ("100.00", "50.00", "50.00", "100.00")),
            (sat.count, (1, 3, -2, "-66.67")),
        ):
            self.assertEqual(
                (comp.current, comp.prior, comp.delta, comp.percent_change),
                tuple(Decimal(str(v)) for v in want))
        self.assertEqual(sat.revenue.percent_change, Decimal("100.00"))
        self.assertEqual(set(mon.deltas), {"count", "appointment_value", "revenue"})

    def test_percent_change_none_when_prior_zero(self):
        wed = prior_busiest(self.salon, START, END).by_weekday[2]
        self.assertEqual((wed.count.prior, wed.count.delta), (Decimal(0), Decimal(1)))
        for comp in (wed.count, wed.appointment_value, wed.revenue):
            self.assertIsNone(comp.percent_change)

    def test_salon_isolation_and_reversed_window(self):
        self._appt(START, hour=16, staff=self.other_staff)
        self._sale(START, "999.00", salon=self.other)
        mon = prior_busiest(self.salon, START, END).by_weekday[0]
        self.assertEqual((mon.count.current, mon.revenue.current),
                         (Decimal(2), Decimal("100.00")))
        with self.assertRaises(ValueError): prior_busiest(self.salon, END, START)
        with self.assertRaises(ValueError):
            export_prior_busiest_csv(self.salon, END, START)


class PriorBusiestExportTests(_Base):
    def test_dict_shape_values_and_csv_agreement(self):
        records = export_prior_busiest(self.salon, START, END)
        self.assertEqual(len(records), 7)
        for record in records: self.assertEqual(list(record), PRIOR_BUSIEST_FIELDNAMES)
        self.assertEqual([r["weekday"] for r in records], list(range(7)))
        mon = records[0]
        self.assertEqual((mon["current_count"], mon["prior_count"],
                          mon["count_delta"], mon["count_percent_change"]),
                         (2, 1, 1, "100.00"))
        self.assertEqual(mon["current_revenue"], "100.00")
        self.assertEqual(mon["prior_start_date"], PRIOR_START.isoformat())
        self.assertEqual(records[2]["count_percent_change"], "")
        rows = list(csv.DictReader(io.StringIO(
            export_prior_busiest_csv(self.salon, START, END))))
        self.assertEqual(rows, [{k: str(v) for k, v in r.items()} for r in records])


class ExportPriorBusiestCommandTests(_Base):
    def test_stdout_string_args_and_file_match_service(self):
        want = export_prior_busiest_csv(self.salon, START, END)
        out = io.StringIO()
        call_command("export_prior_busiest", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        call_command("export_prior_busiest", "--salon-id", str(self.salon.pk),
                     "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), stdout=out)
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_busiest.csv")
            call_command("export_prior_busiest", salon_id=self.salon.pk,
                         start_date=START, end_date=END, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh: written = fh.read()
        self.assertEqual(written, want)
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_bad_dates_and_reversed_raise(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_busiest", salon_id=self.salon.pk + 999,
                         start_date=START, end_date=END, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_busiest", salon_id=self.salon.pk,
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_busiest", "--salon-id", str(self.salon.pk),
                         "--start-date", "2026-13-40",
                         "--end-date", END.isoformat(), stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_busiest", salon_id=self.salon.pk,
                         start_date=END, end_date=START, stdout=io.StringIO())
