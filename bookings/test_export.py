import datetime
from decimal import Decimal

from django.test import TestCase

from bookings.export import EXPORT_FIELDNAMES, export_appointments
from bookings.models import Appointment
from clients.models import Client
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class ExportTestCase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.level = StaffLevel.objects.create(salon=self.salon, name="Level 6")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One", staff_level=self.level
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level, amount=Decimal("85.00")
        )

    def _appt(self, day=DAY, start_h=11, end_h=12, **kw):
        kw.setdefault("client", self.client)
        kw.setdefault("staff_member", self.staff)
        kw.setdefault("service", self.service)
        return Appointment.objects.create(
            start=at(day, start_h), end=at(day, end_h), **kw
        )


class RowShapeTests(ExportTestCase):
    def test_row_carries_contract_fields_and_price_book_price(self):
        appt = self._appt(status=Appointment.Status.CONFIRMED)
        (row,) = export_appointments(self.salon, DAY, DAY)
        self.assertEqual(list(row.keys()), EXPORT_FIELDNAMES)
        self.assertEqual(row["id"], appt.pk)
        self.assertEqual(row["client_id"], self.client.pk)
        self.assertEqual(row["staff_member_id"], self.staff.pk)
        self.assertEqual(row["service_id"], self.service.pk)
        self.assertEqual(row["service_name"], "Haircut")
        self.assertEqual(row["start"], at(DAY, 11).isoformat())
        self.assertEqual(row["end"], at(DAY, 12).isoformat())
        self.assertEqual(row["status"], "confirmed")
        self.assertEqual(row["price"], "85.00")

    def test_rows_ordered_by_start_then_id(self):
        later = self._appt(start_h=14, end_h=15)
        earlier = self._appt(start_h=9, end_h=10)
        rows = export_appointments(self.salon, DAY, DAY)
        self.assertEqual([r["id"] for r in rows], [earlier.pk, later.pk])

    def test_price_is_none_without_level_or_price_row(self):
        no_level = StaffMember.objects.create(
            salon=self.salon, display_name="No Level"
        )
        self._appt(staff_member=no_level)
        (row,) = export_appointments(self.salon, DAY, DAY)
        self.assertIsNone(row["price"])
        # An inactive price row does not count as the current price.
        ServicePrice.objects.filter(service=self.service).update(active=False)
        self._appt(start_h=14, end_h=15)
        rows = export_appointments(self.salon, DAY, DAY)
        self.assertEqual([r["price"] for r in rows], [None, None])


class RangeFilteringTests(ExportTestCase):
    def test_range_bounds_are_inclusive_local_dates(self):
        before = DAY - datetime.timedelta(days=1)
        after = DAY + datetime.timedelta(days=2)
        self._appt(day=before)
        first = self._appt(day=DAY)
        last = self._appt(day=DAY + datetime.timedelta(days=1))
        self._appt(day=after)
        rows = export_appointments(
            self.salon, DAY, DAY + datetime.timedelta(days=1)
        )
        self.assertEqual([r["id"] for r in rows], [first.pk, last.pk])

    def test_omitted_end_date_is_a_single_day(self):
        self._appt()
        self._appt(day=DAY + datetime.timedelta(days=1))
        rows = export_appointments(self.salon, DAY)
        self.assertEqual(len(rows), 1)

    def test_empty_and_reversed_ranges_export_empty(self):
        self._appt()
        empty_day = DAY + datetime.timedelta(days=7)
        self.assertEqual(export_appointments(self.salon, empty_day, empty_day), [])
        self.assertEqual(
            export_appointments(
                self.salon, DAY + datetime.timedelta(days=1), DAY
            ),
            [],
        )
        self.assertEqual(export_appointments(None, DAY, DAY), [])

    def test_other_salons_appointments_are_not_exported(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        outsider_staff = StaffMember.objects.create(
            salon=other, display_name="Outsider"
        )
        outsider_client = Client.objects.create(
            salon=other, first_name="Outside", last_name="Client"
        )
        self._appt(client=outsider_client, staff_member=outsider_staff)
        self._appt()
        rows = export_appointments(self.salon, DAY, DAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["client_id"], self.client.pk)

    def test_range_uses_salon_local_dates(self):
        # 01:00 UTC on Nov 3 is 20:00 EST on Nov 2 in New York:
        # the appointment belongs to the salon-local Nov 2.
        salon = Salon.objects.create(
            name="Local Salon", timezone="America/New_York"
        )
        staff = StaffMember.objects.create(salon=salon, display_name="Local")
        client = Client.objects.create(
            salon=salon, first_name="Local", last_name="Client"
        )
        Appointment.objects.create(
            client=client, staff_member=staff, service=self.service,
            start=at(DAY + datetime.timedelta(days=1), 1),
            end=at(DAY + datetime.timedelta(days=1), 2),
        )
        self.assertEqual(len(export_appointments(salon, DAY, DAY)), 1)
        self.assertEqual(
            export_appointments(salon, DAY + datetime.timedelta(days=1),
                                DAY + datetime.timedelta(days=1)),
            [],
        )


class SnapshotAndStatusTests(ExportTestCase):
    def test_snapshot_name_when_service_fk_is_null(self):
        appt = Appointment.objects.create(
            client=self.client, staff_member=self.staff, service=None,
            service_name="Legacy Treatment",
            start=at(DAY, 11), end=at(DAY, 12),
        )
        (row,) = export_appointments(self.salon, DAY, DAY)
        self.assertEqual(row["id"], appt.pk)
        self.assertIsNone(row["service_id"])
        self.assertEqual(row["service_name"], "Legacy Treatment")
        self.assertIsNone(row["price"])

    def test_cancelled_included_by_default_excluded_on_request(self):
        # Documented choice: an exit export is complete by default,
        # so cancelled rows are included (with their status); the
        # day-book rule is available via include_cancelled=False.
        cancelled = self._appt(status=Appointment.Status.CANCELLED)
        booked = self._appt(start_h=14, end_h=15)
        rows = export_appointments(self.salon, DAY, DAY)
        self.assertEqual([r["id"] for r in rows], [cancelled.pk, booked.pk])
        rows = export_appointments(self.salon, DAY, DAY, include_cancelled=False)
        self.assertEqual([r["id"] for r in rows], [booked.pk])
