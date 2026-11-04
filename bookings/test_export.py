import csv
import datetime
import io
import json
from decimal import Decimal

from django.test import TestCase

from bookings.export import (
    EXPORT_FIELDNAMES,
    export_appointments,
    export_appointments_csv,
)
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


class ClientFilterTests(ExportTestCase):
    def setUp(self):
        super().setUp()
        self.client2 = Client.objects.create(
            salon=self.salon, first_name="Second", last_name="Client"
        )
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two", staff_level=self.level
        )
        self.one = self._appt(start_h=9, end_h=10)
        self.two = self._appt(start_h=11, end_h=12, client=self.client2)
        self.one_cancelled = self._appt(
            start_h=13, end_h=14, status=Appointment.Status.CANCELLED
        )
        self.two_other_staff = self._appt(
            start_h=15, end_h=16, client=self.client2,
            staff_member=self.staff2,
        )

    def _ids(self, rows):
        return [row["id"] for row in rows]

    def test_default_is_salon_wide_and_unchanged(self):
        rows = export_appointments(self.salon, DAY, DAY)
        self.assertEqual(
            self._ids(rows),
            [self.one.pk, self.two.pk, self.one_cancelled.pk,
             self.two_other_staff.pk],
        )
        self.assertEqual(
            rows, export_appointments(self.salon, DAY, DAY, client=None))
        for row in rows:
            self.assertEqual(list(row.keys()), EXPORT_FIELDNAMES)

    def test_filter_by_instance(self):
        rows = export_appointments(self.salon, DAY, DAY, client=self.client)
        self.assertEqual(
            self._ids(rows), [self.one.pk, self.one_cancelled.pk])

    def test_filter_by_pk(self):
        rows = export_appointments(
            self.salon, DAY, DAY, client=self.client2.pk)
        self.assertEqual(
            self._ids(rows), [self.two.pk, self.two_other_staff.pk])

    def test_filter_other_salon_client_exports_empty(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        outsider = Client.objects.create(
            salon=other, first_name="Outside", last_name="Client")
        self.assertEqual(
            export_appointments(self.salon, DAY, DAY, client=outsider), [])

    def test_filter_composes_with_staff_and_include_cancelled(self):
        rows = export_appointments(
            self.salon, DAY, DAY, include_cancelled=False,
            staff_member=self.staff2, client=self.client2)
        self.assertEqual(self._ids(rows), [self.two_other_staff.pk])
        rows = export_appointments(
            self.salon, DAY, DAY, staff_member=self.staff,
            client=self.client2)
        self.assertEqual(self._ids(rows), [self.two.pk])

    def test_csv_filtered_by_client(self):
        text = export_appointments_csv(
            self.salon, DAY, DAY, client=self.client2)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            [int(row["id"]) for row in parsed],
            [self.two.pk, self.two_other_staff.pk])
        self.assertEqual(
            [row["client_id"] for row in parsed],
            [str(self.client2.pk), str(self.client2.pk)])
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))

    def test_csv_default_matches_service_rows(self):
        text = export_appointments_csv(self.salon, DAY, DAY)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            [int(row["id"]) for row in parsed],
            self._ids(export_appointments(self.salon, DAY, DAY)))


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


class CompletenessTests(ExportTestCase):
    """Every concrete Appointment field appears and round-trips."""

    # Model field name -> export key(s) carrying it verbatim.
    FIELD_TO_KEYS = {
        "id": ["id"],
        "external_id": ["external_id"],
        "client": ["client_id"],
        "staff_member": ["staff_member_id"],
        "service": ["service_id"],
        "service_name": ["service_name", "service_name_snapshot"],
        "start": ["start"],
        "end": ["end"],
        "status": ["status"],
        "origin": ["origin"],
        "price_override": ["price_override"],
        "payload": ["payload"],
        "created_at": ["created_at"],
        "updated_at": ["updated_at"],
    }

    def test_every_concrete_model_field_is_exported(self):
        concrete = {f.name for f in Appointment._meta.concrete_fields}
        self.assertEqual(concrete, set(self.FIELD_TO_KEYS))
        for keys in self.FIELD_TO_KEYS.values():
            for key in keys:
                self.assertIn(key, EXPORT_FIELDNAMES)
        # "price" is the only export key that is not a model field.
        exported = {k for keys in self.FIELD_TO_KEYS.values() for k in keys}
        self.assertEqual(set(EXPORT_FIELDNAMES) - exported, {"price"})

    def test_all_stored_fields_round_trip_verbatim(self):
        payload = {"price": "999", "source": "audit",
                   "nested": {"tags": ["a", "b"], "n": 3}}
        appt = self._appt(
            external_id="ext-appt-123",
            origin=Appointment.Origin.ONLINE,
            price_override=Decimal("70.50"),
            payload=payload,
            service_name="Snapshot Name",
            status=Appointment.Status.CONFIRMED,
        )
        appt.refresh_from_db()
        (row,) = export_appointments(self.salon, DAY, DAY)
        self.assertEqual(list(row.keys()), EXPORT_FIELDNAMES)
        self.assertEqual(row["external_id"], "ext-appt-123")
        self.assertEqual(row["origin"], "online")
        self.assertEqual(row["price_override"], "70.50")
        self.assertEqual(Decimal(row["price_override"]), appt.price_override)
        self.assertEqual(row["payload"], payload)
        # Resolved name still wins for service_name; snapshot verbatim.
        self.assertEqual(row["service_name"], "Haircut")
        self.assertEqual(row["service_name_snapshot"], "Snapshot Name")
        self.assertEqual(row["created_at"], appt.created_at.isoformat())
        self.assertEqual(row["updated_at"], appt.updated_at.isoformat())
        # Whole row survives a JSON round-trip unchanged.
        self.assertEqual(json.loads(json.dumps(row)), row)

    def test_defaults_round_trip_verbatim(self):
        self._appt()
        (row,) = export_appointments(self.salon, DAY, DAY)
        self.assertEqual(row["external_id"], "")
        self.assertEqual(row["origin"], "unknown")
        self.assertIsNone(row["price_override"])
        self.assertEqual(row["payload"], {})
        self.assertEqual(row["service_name_snapshot"], "")
        self.assertIsNotNone(row["created_at"])
        self.assertIsNotNone(row["updated_at"])
