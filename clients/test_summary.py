import datetime
from decimal import Decimal

from django.test import TestCase

from bookings.models import Appointment, AppointmentNote
from checkout.models import Sale, SaleItem
from clients.models import Client, ClientNote
from clients.summary import ClientVisitSummary, client_summary, client_visit_summary
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def at(day_offset, hour=9):
    return NOW + datetime.timedelta(days=day_offset, hours=hour - 12)


class ClientSummaryBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        self.other = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )

    def _appt(self, start, client=None, **kw):
        return Appointment.objects.create(
            client=client or self.client,
            staff_member=self.staff,
            service=self.service,
            start=start,
            end=start + datetime.timedelta(minutes=45),
            **kw,
        )

    def _sale(self, client=None, status=Sale.Status.COMPLETED, items=()):
        sale = Sale.objects.create(
            salon=self.salon, client=client or self.client, status=status
        )
        for price, qty in items:
            SaleItem.objects.create(
                sale=sale, kind=SaleItem.Kind.SERVICE,
                unit_price=Decimal(price), quantity=qty,
            )
        return sale


class VisitsTests(ClientSummaryBase):
    def test_total_visits_excludes_cancelled_only(self):
        self._appt(at(-10), status=Appointment.Status.COMPLETED)
        self._appt(at(-1), status=Appointment.Status.NO_SHOW)
        self._appt(at(3), status=Appointment.Status.BOOKED)
        self._appt(at(-2), status=Appointment.Status.CANCELLED)
        self._appt(at(4), status=Appointment.Status.CANCELLED)
        summary = client_visit_summary(self.client, now=NOW)
        self.assertIsInstance(summary, ClientVisitSummary)
        self.assertEqual(summary.total_visits, 3)
        self.assertEqual(summary.client, self.client)

    def test_last_visit_is_latest_past_non_cancelled_start(self):
        self._appt(at(-10))
        latest = self._appt(at(-1))
        # A later cancelled appointment must not become last visit:
        self._appt(
            NOW - datetime.timedelta(hours=1),
            status=Appointment.Status.CANCELLED,
        )
        self._appt(at(3))  # future is not a last visit
        summary = client_visit_summary(self.client, now=NOW)
        self.assertEqual(summary.last_visit, latest.start)
        self.assertEqual(summary.last_visit_date, latest.start.date())

    def test_next_appointment_is_soonest_future_non_cancelled(self):
        self._appt(at(-1))
        self._appt(at(1), status=Appointment.Status.CANCELLED)
        sooner = self._appt(at(2))
        self._appt(at(5))
        summary = client_visit_summary(self.client, now=NOW)
        self.assertEqual(summary.next_appointment, sooner)
        self.assertEqual(summary.next_appointment_start, sooner.start)

    def test_exactly_now_counts_as_next_not_last(self):
        at_now = self._appt(NOW)
        summary = client_visit_summary(self.client, now=NOW)
        self.assertEqual(summary.next_appointment, at_now)
        self.assertIsNone(summary.last_visit)

    def test_empty_client_has_zeroes_and_nones(self):
        self._appt(at(-1), client=self.other)
        summary = client_visit_summary(self.client, now=NOW)
        self.assertEqual(summary.total_visits, 0)
        self.assertIsNone(summary.last_visit)
        self.assertIsNone(summary.last_visit_date)
        self.assertIsNone(summary.next_appointment)
        self.assertEqual(summary.lifetime_spend, Decimal("0.00"))
        self.assertEqual(summary.record_note_count, 0)
        self.assertEqual(summary.appointment_note_count, 0)

    def test_none_client_raises(self):
        with self.assertRaises(ValueError):
            client_visit_summary(None, now=NOW)


class SpendTests(ClientSummaryBase):
    def test_lifetime_spend_sums_non_voided_sale_items(self):
        self._sale(items=[("85.00", 1), ("20.00", 2)])  # 125.00
        self._sale(status=Sale.Status.OPEN, items=[("10.00", 1)])
        summary = client_visit_summary(self.client, now=NOW)
        self.assertEqual(summary.lifetime_spend, Decimal("135.00"))
        self.assertEqual(summary.total_spend, Decimal("135.00"))

    def test_voided_sales_excluded_from_spend(self):
        self._sale(items=[("50.00", 1)])
        self._sale(status=Sale.Status.VOIDED, items=[("999.00", 1)])
        summary = client_visit_summary(self.client, now=NOW)
        self.assertEqual(summary.lifetime_spend, Decimal("50.00"))

    def test_spend_isolated_to_this_client(self):
        self._sale(items=[("40.00", 1)])
        self._sale(client=self.other, items=[("70.00", 1)])
        # A sale with no client link attributes to nobody.
        orphan = Sale.objects.create(salon=self.salon, client=None)
        SaleItem.objects.create(
            sale=orphan, kind=SaleItem.Kind.PRODUCT,
            unit_price=Decimal("60.00"), quantity=1,
        )
        summary = client_visit_summary(self.client, now=NOW)
        self.assertEqual(summary.lifetime_spend, Decimal("40.00"))
        other = client_visit_summary(self.other, now=NOW)
        self.assertEqual(other.lifetime_spend, Decimal("70.00"))


class NoteCountTests(ClientSummaryBase):
    def test_record_and_appointment_note_counts_stay_distinct(self):
        appt = self._appt(at(-1))
        other_appt = self._appt(at(-2))
        ClientNote.objects.create(client=self.client, body="Record one")
        ClientNote.objects.create(client=self.client, body="Record two")
        AppointmentNote.objects.create(appointment=appt, body="Appt only")
        AppointmentNote.objects.create(appointment=other_appt, body="Appt two")
        AppointmentNote.objects.create(appointment=other_appt, body="Appt 3")
        summary = client_visit_summary(self.client, now=NOW)
        self.assertEqual(summary.record_note_count, 2)
        self.assertEqual(summary.client_record_note_count, 2)
        self.assertEqual(summary.appointment_note_count, 3)

    def test_notes_of_other_clients_never_count(self):
        other_appt = self._appt(at(-1), client=self.other)
        ClientNote.objects.create(client=self.other, body="Theirs")
        AppointmentNote.objects.create(appointment=other_appt, body="Theirs")
        ClientNote.objects.create(client=self.client, body="Mine")
        summary = client_visit_summary(self.client, now=NOW)
        self.assertEqual(summary.record_note_count, 1)
        self.assertEqual(summary.appointment_note_count, 0)


class IsolationAndAliasTests(ClientSummaryBase):
    def test_appointments_of_other_client_never_count(self):
        self._appt(at(-5), client=self.other)
        self._appt(at(5), client=self.other)
        mine = self._appt(at(-1))
        summary = client_visit_summary(self.client, now=NOW)
        self.assertEqual(summary.total_visits, 1)
        self.assertEqual(summary.last_visit, mine.start)
        self.assertIsNone(summary.next_appointment)

    def test_alias_matches_main_function(self):
        self._appt(at(-1))
        self.assertEqual(
            client_summary(self.client, now=NOW),
            client_visit_summary(self.client, now=NOW),
        )

    def test_summary_is_read_only(self):
        self._appt(at(-1))
        self._sale(items=[("25.00", 1)])
        before = (
            Appointment.objects.count(), Sale.objects.count(),
            SaleItem.objects.count(), ClientNote.objects.count(),
            AppointmentNote.objects.count(),
        )
        client_visit_summary(self.client, now=NOW)
        after = (
            Appointment.objects.count(), Sale.objects.count(),
            SaleItem.objects.count(), ClientNote.objects.count(),
            AppointmentNote.objects.count(),
        )
        self.assertEqual(before, after)
