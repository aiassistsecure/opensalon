from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from checkout.models import Sale, SaleItem
from clients.models import Client
from insights.services import (
    BusiestDay,
    FutureAppointmentsValue,
    RevenueSplit,
    busiest_days,
    busiest_days_by_revenue,
    future_appointments_value,
    last_7_days_revenue_split,
)
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import StaffMember


class Last7DaysRevenueSplitTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.today = timezone.now().date()

    def _sale(self, salon=None, *, status=Sale.Status.COMPLETED, when=None,
              completed=True):
        sale = Sale.objects.create(salon=salon or self.salon, status=status)
        stamp = when or timezone.now()
        updates = {"created_at": stamp}
        if completed:
            updates["completed_at"] = stamp
        Sale.objects.filter(pk=sale.pk).update(**updates)
        sale.refresh_from_db()
        return sale

    def _item(self, sale, kind, price, quantity=1):
        return SaleItem.objects.create(
            sale=sale, kind=kind, quantity=quantity,
            unit_price=Decimal(price),
        )

    def test_split_service_vs_retail_with_quantities(self):
        sale = self._sale()
        self._item(sale, SaleItem.Kind.SERVICE, "85.00")
        self._item(sale, SaleItem.Kind.PRODUCT, "24.00", quantity=2)
        result = last_7_days_revenue_split(self.salon, today=self.today)
        self.assertIsInstance(result, RevenueSplit)
        self.assertEqual(result.service, Decimal("85.00"))
        self.assertEqual(result.retail, Decimal("48.00"))
        self.assertEqual(result.series, Decimal("0.00"))
        self.assertEqual(result.total, Decimal("133.00"))
        self.assertEqual(result.end_date, self.today)
        self.assertEqual(result.start_date, self.today - timedelta(days=6))
        self.assertEqual(result.days, 7)

    def test_split_includes_series_with_quantities(self):
        sale = self._sale()
        self._item(sale, SaleItem.Kind.SERVICE, "85.00")
        self._item(sale, SaleItem.Kind.PRODUCT, "24.00", quantity=2)
        self._item(sale, SaleItem.Kind.SERIES, "150.00", quantity=2)
        self._item(sale, SaleItem.Kind.SERIES, "50.00")
        result = last_7_days_revenue_split(self.salon, today=self.today)
        self.assertEqual(result.service, Decimal("85.00"))
        self.assertEqual(result.retail, Decimal("48.00"))
        self.assertEqual(result.series, Decimal("350.00"))
        self.assertEqual(result.total, Decimal("483.00"))
        self.assertEqual(
            result.total, result.service + result.retail + result.series
        )

    def test_series_only_sale_counts_toward_series_and_total(self):
        sale = self._sale()
        self._item(sale, SaleItem.Kind.SERIES, "200.00")
        result = last_7_days_revenue_split(self.salon, today=self.today)
        self.assertEqual(result.service, Decimal("0.00"))
        self.assertEqual(result.retail, Decimal("0.00"))
        self.assertEqual(result.series, Decimal("200.00"))
        self.assertEqual(result.total, Decimal("200.00"))

    def test_no_sales_returns_zeroes_not_none(self):
        result = last_7_days_revenue_split(self.salon, today=self.today)
        self.assertEqual(result.service, Decimal("0.00"))
        self.assertEqual(result.retail, Decimal("0.00"))
        self.assertEqual(result.series, Decimal("0.00"))
        self.assertEqual(result.total, Decimal("0.00"))

    def test_window_includes_day_7_boundary_and_excludes_older(self):
        edge = self._sale(when=timezone.now() - timedelta(days=6))
        self._item(edge, SaleItem.Kind.SERVICE, "50.00")
        old = self._sale(when=timezone.now() - timedelta(days=7))
        self._item(old, SaleItem.Kind.SERVICE, "999.00")
        result = last_7_days_revenue_split(self.salon, today=self.today)
        self.assertEqual(result.service, Decimal("50.00"))

    def test_open_and_voided_sales_excluded(self):
        for status in (Sale.Status.OPEN, Sale.Status.VOIDED):
            sale = self._sale(status=status)
            self._item(sale, SaleItem.Kind.PRODUCT, "10.00")
        result = last_7_days_revenue_split(self.salon, today=self.today)
        self.assertEqual(result.total, Decimal("0.00"))

    def test_other_salon_sales_excluded(self):
        sale = self._sale(salon=self.other)
        self._item(sale, SaleItem.Kind.SERVICE, "70.00")
        result = last_7_days_revenue_split(self.salon, today=self.today)
        self.assertEqual(result.total, Decimal("0.00"))

    def test_completed_sale_without_completed_at_uses_created_at(self):
        sale = self._sale(completed=False)
        Sale.objects.filter(pk=sale.pk).update(completed_at=None)
        self._item(sale, SaleItem.Kind.SERVICE, "40.00")
        result = last_7_days_revenue_split(self.salon, today=self.today)
        self.assertEqual(result.service, Decimal("40.00"))


class FutureAppointmentsValueTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.level = StaffLevel.objects.create(salon=self.salon, name="Level 1")
        self.other_level = StaffLevel.objects.create(
            salon=self.other, name="Level 1"
        )
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            staff_level=self.level,
        )
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other Stylist",
            staff_level=self.other_level,
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        self.other_client = Client.objects.create(
            salon=self.other, first_name="Other", last_name="Client"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        other_category = ServiceCategory.objects.create(
            salon=self.other, name="Hair"
        )
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        self.other_service = Service.objects.create(
            category=other_category, name="Haircut", service_minutes=45
        )
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"),
        )
        ServicePrice.objects.create(
            service=self.other_service, staff_level=self.other_level,
            amount=Decimal("85.00"),
        )
        # Fixed as_of: noon UTC, so day buckets are unambiguous.
        self.as_of = datetime(2026, 11, 2, 12, 0, tzinfo=ZoneInfo("UTC"))

    def _appt(self, *, staff=None, client=None, service=None, when=None,
              status=Appointment.Status.BOOKED):
        start = when or (self.as_of + timedelta(days=1))
        return Appointment.objects.create(
            client=client or self.client,
            staff_member=staff or self.staff,
            service=service or self.service,
            start=start, end=start + timedelta(minutes=45), status=status,
        )

    def test_total_and_count_sum_priced_future_appointments(self):
        self._appt(when=self.as_of + timedelta(days=1))
        self._appt(when=self.as_of + timedelta(days=3))
        result = future_appointments_value(self.salon, self.as_of)
        self.assertIsInstance(result, FutureAppointmentsValue)
        self.assertEqual(result.total, Decimal("170.00"))
        self.assertEqual(result.count, 2)
        self.assertEqual(result.as_of, self.as_of)
        self.assertEqual(result.start_date, self.as_of.date())
        self.assertEqual(result.end_date, self.as_of.date() + timedelta(days=6))

    def test_per_day_breakdown_covers_next_7_days_with_zeroes(self):
        self._appt(when=self.as_of + timedelta(hours=2))
        self._appt(when=self.as_of + timedelta(days=2))
        self._appt(when=self.as_of + timedelta(days=2, hours=3))
        result = future_appointments_value(self.salon, self.as_of)
        self.assertEqual(len(result.days), 7)
        self.assertEqual(result.days[0].day, self.as_of.date())
        self.assertEqual(result.days[0].value, Decimal("85.00"))
        self.assertEqual(result.days[0].count, 1)
        self.assertEqual(result.days[1].value, Decimal("0.00"))
        self.assertEqual(result.days[1].count, 0)
        self.assertEqual(result.days[2].value, Decimal("170.00"))
        self.assertEqual(result.days[2].count, 2)
        self.assertEqual(result.days[6].day, result.end_date)

    def test_beyond_7_days_counts_toward_total_but_no_day_entry(self):
        self._appt(when=self.as_of + timedelta(days=30))
        result = future_appointments_value(self.salon, self.as_of)
        self.assertEqual(result.total, Decimal("85.00"))
        self.assertEqual(result.count, 1)
        self.assertTrue(all(entry.count == 0 for entry in result.days))

    def test_no_appointments_returns_zeroes_not_none(self):
        result = future_appointments_value(self.salon, self.as_of)
        self.assertEqual(result.total, Decimal("0.00"))
        self.assertEqual(result.count, 0)
        self.assertEqual(len(result.days), 7)

    def test_past_and_exact_boundary(self):
        self._appt(when=self.as_of - timedelta(minutes=1))
        self._appt(when=self.as_of)
        result = future_appointments_value(self.salon, self.as_of)
        self.assertEqual(result.total, Decimal("85.00"))
        self.assertEqual(result.count, 1)

    def test_cancelled_excluded_other_statuses_included(self):
        self._appt(status=Appointment.Status.CANCELLED)
        self._appt(status=Appointment.Status.CONFIRMED)
        self._appt(status=Appointment.Status.NO_SHOW)
        result = future_appointments_value(self.salon, self.as_of)
        self.assertEqual(result.total, Decimal("170.00"))
        self.assertEqual(result.count, 2)

    def test_other_salon_appointments_excluded(self):
        self._appt(staff=self.other_staff, client=self.other_client,
                   service=self.other_service)
        result = future_appointments_value(self.salon, self.as_of)
        self.assertEqual(result.total, Decimal("0.00"))
        self.assertEqual(result.count, 0)

    def test_price_comes_from_staff_level_price_book(self):
        senior = StaffLevel.objects.create(salon=self.salon, name="Senior")
        ServicePrice.objects.create(
            service=self.service, staff_level=senior, amount=Decimal("120.00"),
        )
        senior_staff = StaffMember.objects.create(
            salon=self.salon, display_name="Senior Stylist",
            staff_level=senior,
        )
        self._appt(staff=senior_staff)
        self._appt()
        result = future_appointments_value(self.salon, self.as_of)
        self.assertEqual(result.total, Decimal("205.00"))

    def test_unpriced_appointment_counts_but_adds_zero(self):
        levelless = StaffMember.objects.create(
            salon=self.salon, display_name="No Level"
        )
        self._appt(staff=levelless)
        self._appt()
        result = future_appointments_value(self.salon, self.as_of)
        self.assertEqual(result.total, Decimal("85.00"))
        self.assertEqual(result.count, 2)

    def test_inactive_price_is_not_used(self):
        ServicePrice.objects.filter(
            service=self.service, staff_level=self.level,
        ).update(active=False)
        self._appt()
        result = future_appointments_value(self.salon, self.as_of)
        self.assertEqual(result.total, Decimal("0.00"))
        self.assertEqual(result.count, 1)

    def test_default_as_of_uses_now(self):
        self._appt(when=timezone.now() + timedelta(days=1))
        self._appt(when=timezone.now() - timedelta(days=1))
        result = future_appointments_value(self.salon)
        self.assertEqual(result.total, Decimal("85.00"))
        self.assertEqual(result.count, 1)



class BusiestDaysTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.level = StaffLevel.objects.create(salon=self.salon, name="Level 1")
        self.other_level = StaffLevel.objects.create(
            salon=self.other, name="Level 1"
        )
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            staff_level=self.level,
        )
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other Stylist",
            staff_level=self.other_level,
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"),
        )
        # Fixed week: Monday 2026-11-02 through Sunday 2026-11-08.
        self.since = date(2026, 11, 2)
        self.until = date(2026, 11, 8)

    def _appt(self, *, day_offset=0, hour=10, staff=None,
              status=Appointment.Status.BOOKED):
        start = datetime(
            2026, 11, 2 + day_offset, hour, 0, tzinfo=ZoneInfo("UTC")
        )
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.staff,
            service=self.service, start=start,
            end=start + timedelta(minutes=45), status=status,
        )

    def _sale(self, *, day_offset=0, salon=None,
              status=Sale.Status.COMPLETED):
        sale = Sale.objects.create(salon=salon or self.salon, status=status)
        stamp = datetime(
            2026, 11, 2 + day_offset, 12, 0, tzinfo=ZoneInfo("UTC")
        )
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp
        )
        sale.refresh_from_db()
        return sale

    def _by_weekday(self, result):
        return {entry.weekday: entry for entry in result}

    def test_weekday_bucketing_counts_and_appointment_value(self):
        self._appt(day_offset=0)  # Monday
        self._appt(day_offset=0, hour=14)  # Monday
        self._appt(day_offset=5)  # Saturday
        result = busiest_days(self.salon, self.since, self.until)
        self.assertEqual(len(result), 7)
        self.assertTrue(all(isinstance(e, BusiestDay) for e in result))
        by_weekday = self._by_weekday(result)
        self.assertEqual(by_weekday[0].weekday_name, "Monday")
        self.assertEqual(by_weekday[0].count, 2)
        self.assertEqual(by_weekday[0].appointment_value, Decimal("170.00"))
        self.assertEqual(by_weekday[5].weekday_name, "Saturday")
        self.assertEqual(by_weekday[5].count, 1)
        self.assertEqual(by_weekday[5].appointment_value, Decimal("85.00"))
        self.assertEqual(by_weekday[2].count, 0)
        self.assertEqual(by_weekday[2].appointment_value, Decimal("0.00"))

    def test_completed_sale_revenue_bucketed_by_weekday(self):
        saturday = self._sale(day_offset=5)
        SaleItem.objects.create(
            sale=saturday, kind=SaleItem.Kind.SERVICE,
            quantity=1, unit_price=Decimal("85.00"),
        )
        SaleItem.objects.create(
            sale=saturday, kind=SaleItem.Kind.PRODUCT,
            quantity=2, unit_price=Decimal("24.00"),
        )
        monday = self._sale(day_offset=0)
        SaleItem.objects.create(
            sale=monday, kind=SaleItem.Kind.SERVICE,
            quantity=1, unit_price=Decimal("50.00"),
        )
        open_sale = self._sale(day_offset=5, status=Sale.Status.OPEN)
        SaleItem.objects.create(
            sale=open_sale, kind=SaleItem.Kind.SERVICE,
            quantity=1, unit_price=Decimal("999.00"),
        )
        by_weekday = self._by_weekday(
            busiest_days(self.salon, self.since, self.until)
        )
        self.assertEqual(by_weekday[5].revenue, Decimal("133.00"))
        self.assertEqual(by_weekday[0].revenue, Decimal("50.00"))
        self.assertEqual(by_weekday[1].revenue, Decimal("0.00"))

    def test_cancelled_excluded_other_statuses_included(self):
        self._appt(day_offset=1, status=Appointment.Status.CANCELLED)
        self._appt(day_offset=1, status=Appointment.Status.CONFIRMED)
        self._appt(day_offset=1, hour=15, status=Appointment.Status.COMPLETED)
        by_weekday = self._by_weekday(
            busiest_days(self.salon, self.since, self.until)
        )
        self.assertEqual(by_weekday[1].count, 2)
        self.assertEqual(by_weekday[1].appointment_value, Decimal("170.00"))

    def test_empty_range_returns_seven_zeroed_weekdays(self):
        result = busiest_days(self.salon, self.since, self.until)
        self.assertEqual(len(result), 7)
        self.assertEqual([e.weekday for e in result], list(range(7)))
        for entry in result:
            self.assertEqual(entry.count, 0)
            self.assertEqual(entry.revenue, Decimal("0.00"))
            self.assertEqual(entry.appointment_value, Decimal("0.00"))

    def test_ordering_by_count_desc_then_weekday(self):
        self._appt(day_offset=5)  # Saturday, 3 appointments
        self._appt(day_offset=5, hour=12)
        self._appt(day_offset=5, hour=16)
        self._appt(day_offset=0)  # Monday, 1 appointment
        self._appt(day_offset=2)  # Wednesday, 1 appointment
        result = busiest_days(self.salon, self.since, self.until)
        self.assertEqual(result[0].weekday, 5)
        self.assertEqual(result[0].count, 3)
        self.assertEqual([e.weekday for e in result[1:3]], [0, 2])
        counts = [e.count for e in result]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_range_bounds_inclusive_and_other_salon_excluded(self):
        self._appt(day_offset=0)  # since bound (Monday)
        self._appt(day_offset=6)  # until bound (Sunday)
        self._appt(day_offset=7)  # Monday after the range
        self._appt(day_offset=-1)  # Sunday before the range
        self._appt(day_offset=0, hour=16, staff=self.other_staff)
        by_weekday = self._by_weekday(
            busiest_days(self.salon, self.since, self.until)
        )
        self.assertEqual(by_weekday[0].count, 1)
        self.assertEqual(by_weekday[6].count, 1)
        self.assertEqual(sum(e.count for e in by_weekday.values()), 2)


class BusiestDaysByRevenueTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        # Fixed week: Monday 2026-11-02 through Sunday 2026-11-08.
        self.since = date(2026, 11, 2)
        self.until = date(2026, 11, 8)

    def _sale_with_item(self, *, day_offset=0, salon=None,
                        status=Sale.Status.COMPLETED, price="0.00",
                        kind=SaleItem.Kind.SERVICE, quantity=1):
        sale = Sale.objects.create(salon=salon or self.salon, status=status)
        stamp = datetime(
            2026, 11, 2 + day_offset, 12, 0, tzinfo=ZoneInfo("UTC")
        )
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp
        )
        SaleItem.objects.create(
            sale=sale, kind=kind, quantity=quantity,
            unit_price=Decimal(price),
        )
        return sale

    def test_orders_by_revenue_desc_not_appointment_count(self):
        # Saturday takings (service + retail) beat Monday's, even
        # though neither day has any appointments in this test.
        self._sale_with_item(day_offset=5, price="85.00")
        self._sale_with_item(
            day_offset=5, price="24.00", quantity=2,
            kind=SaleItem.Kind.PRODUCT,
        )
        self._sale_with_item(day_offset=0, price="50.00")
        result = busiest_days_by_revenue(self.salon, self.since, self.until)
        self.assertEqual(len(result), 7)
        self.assertTrue(all(isinstance(e, BusiestDay) for e in result))
        self.assertEqual(result[0].weekday, 5)
        self.assertEqual(result[0].revenue, Decimal("133.00"))
        self.assertEqual(result[1].weekday, 0)
        self.assertEqual(result[1].revenue, Decimal("50.00"))
        revenues = [e.revenue for e in result]
        self.assertEqual(revenues, sorted(revenues, reverse=True))

    def test_revenue_ties_break_by_weekday_ascending(self):
        self._sale_with_item(day_offset=3, price="40.00")  # Thursday
        self._sale_with_item(day_offset=1, price="40.00")  # Tuesday
        result = busiest_days_by_revenue(self.salon, self.since, self.until)
        self.assertEqual([e.weekday for e in result[:2]], [1, 3])

    def test_only_completed_sales_of_this_salon_count(self):
        self._sale_with_item(day_offset=2, price="60.00")
        self._sale_with_item(
            day_offset=2, price="999.00", status=Sale.Status.OPEN
        )
        self._sale_with_item(
            day_offset=2, price="999.00", status=Sale.Status.VOIDED
        )
        self._sale_with_item(day_offset=4, price="999.00", salon=self.other)
        result = busiest_days_by_revenue(self.salon, self.since, self.until)
        self.assertEqual(result[0].weekday, 2)
        self.assertEqual(result[0].revenue, Decimal("60.00"))
        self.assertEqual(sum(e.revenue for e in result), Decimal("60.00"))

    def test_empty_and_reversed_ranges_return_seven_zeroed_weekdays(self):
        for since, until in ((self.since, self.until),
                             (self.until, self.since)):
            result = busiest_days_by_revenue(self.salon, since, until)
            self.assertEqual([e.weekday for e in result], list(range(7)))
            for entry in result:
                self.assertEqual(entry.revenue, Decimal("0.00"))
                self.assertEqual(entry.count, 0)

    def test_entries_match_busiest_days_fields(self):
        self._sale_with_item(day_offset=6, price="75.00")
        by_revenue = busiest_days_by_revenue(
            self.salon, self.since, self.until
        )
        plain = busiest_days(self.salon, self.since, self.until)
        self.assertEqual(
            {e.weekday: e for e in by_revenue},
            {e.weekday: e for e in plain},
        )
