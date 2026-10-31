from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from bookings.models import Appointment
from checkout.models import Sale, SaleItem
from clients.models import Client
from insights.returning import ReturningRevenue, new_vs_returning_revenue
from saloncore.models import Salon
from team.models import StaffMember

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)  # Monday
END = date(2026, 11, 8)  # Sunday


class NewVsReturningRevenueTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist"
        )
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other Stylist"
        )
        self.returning_client = Client.objects.create(
            salon=self.salon, first_name="Ret", last_name="Urning"
        )
        self.new_client = Client.objects.create(
            salon=self.salon, first_name="New", last_name="Client"
        )
        self.appt_client = Client.objects.create(
            salon=self.salon, first_name="Appt", last_name="First"
        )

    def _sale(self, client=None, *, day, price="50.00", salon=None,
              status=Sale.Status.COMPLETED):
        sale = Sale.objects.create(
            salon=salon or self.salon, client=client, status=status
        )
        stamp = datetime(2026, 11, 2, 12, 0, tzinfo=UTC) + timedelta(days=day)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp
        )
        if price is not None:
            SaleItem.objects.create(
                sale=sale, kind=SaleItem.Kind.SERVICE,
                quantity=1, unit_price=Decimal(price),
            )
        return sale

    def _appt(self, client, *, day, staff=None,
              status=Appointment.Status.COMPLETED):
        start = datetime(2026, 11, 2, 10, 0, tzinfo=UTC) + timedelta(days=day)
        return Appointment.objects.create(
            client=client, staff_member=staff or self.staff,
            start=start, end=start + timedelta(minutes=45),
            status=status,
        )

    def test_returning_new_and_unattributed_sum_to_total(self):
        # Returning: completed sale a week before the window.
        self._sale(self.returning_client, day=-7, price="999.00")
        self._sale(self.returning_client, day=1, price="85.00")
        self._sale(self.returning_client, day=2, price="15.00")
        # New: first-ever sale is inside the window; a second
        # in-window sale stays "new" for this window.
        self._sale(self.new_client, day=0, price="50.00")
        self._sale(self.new_client, day=3, price="10.00")
        # Unattributed: no client link at all.
        self._sale(None, day=1, price="30.00")

        result = new_vs_returning_revenue(self.salon, START, END)
        self.assertIsInstance(result, ReturningRevenue)
        self.assertEqual(result.start_date, START)
        self.assertEqual(result.end_date, END)
        self.assertEqual(result.returning_revenue, Decimal("100.00"))
        self.assertEqual(result.new_revenue, Decimal("60.00"))
        self.assertEqual(result.unattributed_revenue, Decimal("30.00"))
        self.assertEqual(result.total, Decimal("190.00"))
        self.assertEqual(
            result.returning_revenue + result.new_revenue
            + result.unattributed_revenue,
            result.total,
        )
        self.assertEqual(result.returning_sale_count, 2)
        self.assertEqual(result.new_sale_count, 2)
        self.assertEqual(result.unattributed_sale_count, 1)
        self.assertEqual(result.total_sale_count, 5)

    def test_prior_completed_appointment_makes_returning(self):
        self._appt(self.appt_client, day=-5)  # completed, pre-window
        self._sale(self.appt_client, day=0, price="70.00")
        result = new_vs_returning_revenue(self.salon, START, END)
        self.assertEqual(result.returning_revenue, Decimal("70.00"))
        self.assertEqual(result.new_revenue, Decimal("0.00"))

    def test_non_completed_history_does_not_make_returning(self):
        # A voided pre-window sale and a cancelled pre-window
        # appointment are not completed history.
        self._sale(
            self.new_client, day=-6, price="999.00",
            status=Sale.Status.VOIDED,
        )
        self._appt(
            self.new_client, day=-4,
            status=Appointment.Status.CANCELLED,
        )
        self._sale(self.new_client, day=0, price="40.00")
        result = new_vs_returning_revenue(self.salon, START, END)
        self.assertEqual(result.new_revenue, Decimal("40.00"))
        self.assertEqual(result.returning_revenue, Decimal("0.00"))
        self.assertEqual(result.total, Decimal("40.00"))

    def test_history_at_other_salon_does_not_make_returning(self):
        other_client = Client.objects.create(
            salon=self.other, first_name="Cross", last_name="Salon"
        )
        # Same person record belongs to the other salon; its
        # history there must not classify a sale at this salon —
        # and a sale here linked to another salon's client is
        # unattributed, never guessed at.
        self._appt(other_client, day=-5, staff=self.other_staff)
        self._sale(other_client, day=0, price="25.00")
        result = new_vs_returning_revenue(self.salon, START, END)
        self.assertEqual(result.unattributed_revenue, Decimal("25.00"))
        self.assertEqual(result.returning_revenue, Decimal("0.00"))
        self.assertEqual(result.new_revenue, Decimal("0.00"))

    def test_open_voided_and_out_of_window_sales_excluded(self):
        self._sale(self.new_client, day=0, status=Sale.Status.OPEN)
        self._sale(self.new_client, day=0, status=Sale.Status.VOIDED)
        self._sale(self.new_client, day=7, price="999.00")  # after
        self._sale(self.new_client, day=0, price="45.00")  # start bound
        self._sale(self.new_client, day=5, price="5.00")  # inside
        result = new_vs_returning_revenue(self.salon, START, END)
        self.assertEqual(result.new_revenue, Decimal("50.00"))
        self.assertEqual(result.total, Decimal("50.00"))
        self.assertEqual(result.new_sale_count, 2)

    def test_empty_and_reversed_windows_return_zeroes(self):
        for start, end in ((START, END), (END, START)):
            result = new_vs_returning_revenue(self.salon, start, end)
            self.assertEqual(result.total, Decimal("0.00"))
            self.assertEqual(result.returning_revenue, Decimal("0.00"))
            self.assertEqual(result.new_revenue, Decimal("0.00"))
            self.assertEqual(result.unattributed_revenue, Decimal("0.00"))
            self.assertEqual(result.total_sale_count, 0)
