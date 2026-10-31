from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from bookings.models import Appointment
from checkout.models import Sale, SaleItem
from clients.models import Client
from insights.staff_revenue import StaffRevenue, revenue_by_staff
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")


class RevenueByStaffTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff_a = StaffMember.objects.create(
            salon=self.salon, display_name="Alice"
        )
        self.staff_b = StaffMember.objects.create(
            salon=self.salon, display_name="Bob"
        )
        self.client_a = Client.objects.create(
            salon=self.salon, first_name="Ann", last_name="A"
        )
        self.client_b = Client.objects.create(
            salon=self.salon, first_name="Ben", last_name="B"
        )
        self.client_c = Client.objects.create(
            salon=self.salon, first_name="Cat", last_name="C"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.cut = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        self.colour = Service.objects.create(
            category=category, name="Colour", service_minutes=60
        )
        # Fixed week: Monday 2026-11-02 through Sunday 2026-11-08.
        self.start = date(2026, 11, 2)
        self.end = date(2026, 11, 8)

    def _appt(self, client, staff, *, day_offset=0, service=None,
              status=Appointment.Status.BOOKED):
        start = datetime(2026, 11, 2 + day_offset, 10, 0, tzinfo=UTC)
        return Appointment.objects.create(
            client=client, staff_member=staff,
            service=service or self.cut, start=start,
            end=start + timedelta(minutes=45), status=status,
        )

    def _sale(self, client=None, *, day_offset=0,
              status=Sale.Status.COMPLETED, completed=True):
        sale = Sale.objects.create(
            salon=self.salon, client=client, status=status
        )
        stamp = datetime(2026, 11, 2 + day_offset, 12, 0, tzinfo=UTC)
        updates = {"created_at": stamp}
        if completed:
            updates["completed_at"] = stamp
        Sale.objects.filter(pk=sale.pk).update(**updates)
        sale.refresh_from_db()
        return sale

    def _item(self, sale, kind, price, *, quantity=1, service=None):
        return SaleItem.objects.create(
            sale=sale, kind=kind, quantity=quantity,
            unit_price=Decimal(price), service=service,
        )

    def _by_name(self, rows):
        return {row.display_name: row for row in rows}

    def test_two_staff_plus_unattributed_ordered_by_total(self):
        self._appt(self.client_a, self.staff_a, day_offset=1)
        sale_a = self._sale(self.client_a, day_offset=1)
        self._item(sale_a, SaleItem.Kind.SERVICE, "85.00", service=self.cut)
        self._item(sale_a, SaleItem.Kind.PRODUCT, "24.00")
        self._appt(self.client_b, self.staff_b, day_offset=2)
        sale_b = self._sale(self.client_b, day_offset=2)
        self._item(sale_b, SaleItem.Kind.SERVICE, "50.00", service=self.cut)
        sale_c = self._sale(self.client_c, day_offset=3)  # no appointment
        self._item(sale_c, SaleItem.Kind.SERVICE, "30.00", service=self.cut)

        rows = revenue_by_staff(self.salon, self.start, self.end)
        self.assertTrue(all(isinstance(r, StaffRevenue) for r in rows))
        self.assertEqual(
            [r.display_name for r in rows], ["Alice", "Bob", "Unattributed"]
        )
        by_name = self._by_name(rows)
        alice = by_name["Alice"]
        self.assertEqual(alice.staff, self.staff_a)
        self.assertEqual(alice.service_revenue, Decimal("85.00"))
        self.assertEqual(alice.retail_revenue, Decimal("24.00"))
        self.assertEqual(alice.total, Decimal("109.00"))
        self.assertEqual(alice.sale_count, 1)
        self.assertEqual(by_name["Bob"].total, Decimal("50.00"))
        self.assertEqual(by_name["Bob"].sale_count, 1)
        unattributed = by_name["Unattributed"]
        self.assertIsNone(unattributed.staff)
        self.assertEqual(unattributed.total, Decimal("30.00"))
        self.assertEqual(unattributed.sale_count, 1)

    def test_unattributed_row_omitted_when_all_attributed(self):
        self._appt(self.client_a, self.staff_a, day_offset=0)
        sale = self._sale(self.client_a, day_offset=0)
        self._item(sale, SaleItem.Kind.SERVICE, "85.00", service=self.cut)
        rows = revenue_by_staff(self.salon, self.start, self.end)
        self.assertEqual([r.display_name for r in rows], ["Alice"])

    def test_voided_and_open_sales_excluded(self):
        self._appt(self.client_a, self.staff_a, day_offset=0)
        for status in (Sale.Status.VOIDED, Sale.Status.OPEN):
            sale = self._sale(self.client_a, day_offset=0, status=status)
            self._item(sale, SaleItem.Kind.SERVICE, "999.00", service=self.cut)
        sale = self._sale(self.client_c, day_offset=0, status=Sale.Status.VOIDED)
        self._item(sale, SaleItem.Kind.SERVICE, "999.00", service=self.cut)
        self.assertEqual(revenue_by_staff(self.salon, self.start, self.end), [])

    def test_window_boundaries_inclusive(self):
        for client, staff, offset in (
            (self.client_a, self.staff_a, 0),   # start bound
            (self.client_b, self.staff_b, 6),   # end bound
        ):
            self._appt(client, staff, day_offset=offset)
            sale = self._sale(client, day_offset=offset)
            self._item(sale, SaleItem.Kind.SERVICE, "40.00", service=self.cut)
        for offset in (-1, 7):  # outside the window
            self._appt(self.client_c, self.staff_a, day_offset=offset)
            sale = self._sale(self.client_c, day_offset=offset)
            self._item(sale, SaleItem.Kind.SERVICE, "999.00", service=self.cut)
        rows = revenue_by_staff(self.salon, self.start, self.end)
        self.assertEqual(
            {r.display_name: r.total for r in rows},
            {"Alice": Decimal("40.00"), "Bob": Decimal("40.00")},
        )

    def test_empty_and_reversed_windows_return_empty_list(self):
        self.assertEqual(revenue_by_staff(self.salon, self.start, self.end), [])
        self.assertEqual(revenue_by_staff(self.salon, self.end, self.start), [])

    def test_sale_without_completed_at_uses_created_at(self):
        self._appt(self.client_a, self.staff_a, day_offset=1)
        sale = self._sale(self.client_a, day_offset=1, completed=False)
        Sale.objects.filter(pk=sale.pk).update(completed_at=None)
        self._item(sale, SaleItem.Kind.SERVICE, "60.00", service=self.cut)
        rows = revenue_by_staff(self.salon, self.start, self.end)
        self.assertEqual([r.display_name for r in rows], ["Alice"])
        self.assertEqual(rows[0].total, Decimal("60.00"))

    def test_service_mismatch_and_cancelled_appointment_unattributed(self):
        self._appt(self.client_a, self.staff_a, day_offset=0, service=self.colour)
        sale = self._sale(self.client_a, day_offset=0)
        self._item(sale, SaleItem.Kind.SERVICE, "85.00", service=self.cut)
        self._appt(
            self.client_b, self.staff_b, day_offset=0,
            status=Appointment.Status.CANCELLED,
        )
        sale_b = self._sale(self.client_b, day_offset=0)
        self._item(sale_b, SaleItem.Kind.SERVICE, "50.00", service=self.cut)
        rows = revenue_by_staff(self.salon, self.start, self.end)
        self.assertEqual([r.display_name for r in rows], ["Unattributed"])
        self.assertEqual(rows[0].total, Decimal("135.00"))
        self.assertEqual(rows[0].sale_count, 2)

    def test_retail_only_sale_attributes_to_single_staff_that_day(self):
        self._appt(self.client_a, self.staff_a, day_offset=0)
        sale = self._sale(self.client_a, day_offset=0)
        self._item(sale, SaleItem.Kind.PRODUCT, "24.00", quantity=2)
        rows = revenue_by_staff(self.salon, self.start, self.end)
        self.assertEqual([r.display_name for r in rows], ["Alice"])
        self.assertEqual(rows[0].retail_revenue, Decimal("48.00"))
        self.assertEqual(rows[0].service_revenue, Decimal("0.00"))
