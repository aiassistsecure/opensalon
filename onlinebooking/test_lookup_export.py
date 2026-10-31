import csv
import datetime
import io

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.lookup import upcoming_online_bookings
from onlinebooking.lookup_export import (
    EXPORT_FIELDNAMES,
    export_lookup,
    export_lookup_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)  # a Monday


def at(day_offset, hour, minute=0):
    return NOW + datetime.timedelta(days=day_offset, hours=hour - 12, minutes=minute)


class LookupExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Online Stylist", online_bookable=True
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        self.other_client = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )

    def _appt(self, start, client=None, staff=None, service=None, **kw):
        return Appointment.objects.create(
            client=client or self.client,
            staff_member=staff or self.staff,
            service=service or self.service,
            start=start,
            end=start + datetime.timedelta(minutes=45),
            **kw,
        )

    def test_csv_header_columns_and_rows_match_lookup_output(self):
        sooner = self._appt(at(0, 13))
        later = self._appt(at(1, 9), status=Appointment.Status.CONFIRMED)
        text = export_lookup_csv(self.salon, self.client, now=NOW)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(text)))
        expected = list(upcoming_online_bookings(self.salon, self.client, now=NOW))
        self.assertEqual(expected, [sooner, later])
        self.assertEqual([int(r["id"]) for r in parsed], [a.pk for a in expected])
        row = parsed[0]
        self.assertEqual(row["salon_id"], str(self.salon.pk))
        self.assertEqual(row["client_id"], str(self.client.pk))
        self.assertEqual(row["staff_member_id"], str(self.staff.pk))
        self.assertEqual(row["staff_name"], "Online Stylist")
        self.assertEqual(row["service_id"], str(self.service.pk))
        self.assertEqual(row["service_name"], "Haircut")
        self.assertEqual(row["start"], sooner.start.isoformat())
        self.assertEqual(row["end"], sooner.end.isoformat())
        self.assertEqual(row["status"], Appointment.Status.BOOKED)
        records = export_lookup(self.salon, self.client, now=NOW)
        self.assertEqual(list(records[0].keys()), EXPORT_FIELDNAMES)
        self.assertEqual([r["id"] for r in records], [a.pk for a in expected])

    def test_future_only_booked_confirmed_and_exactly_now(self):
        self._appt(at(-1, 9))
        at_now = self._appt(NOW)
        self._appt(at(1, 9), status=Appointment.Status.CANCELLED)
        self._appt(at(1, 10), status=Appointment.Status.COMPLETED)
        self._appt(at(1, 11), status=Appointment.Status.ARRIVED)
        records = export_lookup(self.salon, self.client, now=NOW)
        self.assertEqual([r["id"] for r in records], [at_now.pk])

    def test_no_origin_filter_unlike_salon_wide_upcoming_export(self):
        # Lookup carries every origin through; export_upcoming is
        # ONLINE-only. A phone-origin booking proves the gap filled
        # is the lookup query, not a duplicate of that export.
        phone = self._appt(at(1, 9), origin=Appointment.Origin.PHONE)
        online = self._appt(at(1, 10), origin=Appointment.Origin.ONLINE)
        records = export_lookup(self.salon, self.client, now=NOW)
        self.assertEqual([r["id"] for r in records], [phone.pk, online.pk])
        self.assertEqual(records[0]["origin"], Appointment.Origin.PHONE)

    def test_per_client_scope_and_salon_wide_merge(self):
        mine = self._appt(at(2, 9))
        theirs = self._appt(at(1, 9), client=self.other_client)
        self.assertEqual(
            [r["id"] for r in export_lookup(self.salon, self.client, now=NOW)],
            [mine.pk],
        )
        # Salon-wide: merged across clients, soonest first.
        self.assertEqual(
            [r["id"] for r in export_lookup(self.salon, now=NOW)],
            [theirs.pk, mine.pk],
        )

    def test_salon_isolation(self):
        outsider = Client.objects.create(
            salon=self.other_salon, first_name="Out", last_name="Sider"
        )
        self._appt(at(1, 9), client=outsider)
        mine = self._appt(at(1, 10))
        self.assertEqual(export_lookup(self.salon, outsider, now=NOW), [])
        self.assertEqual(export_lookup(self.other_salon, self.client, now=NOW), [])
        self.assertEqual(
            [r["id"] for r in export_lookup(self.salon, self.client, now=NOW)],
            [mine.pk],
        )

    def test_empty_exports_header_only(self):
        self._appt(at(-1, 9))
        self.assertEqual(export_lookup(self.salon, self.client, now=NOW), [])
        self.assertEqual(export_lookup(None, self.client, now=NOW), [])
        self.assertEqual(export_lookup(self.salon, None, now=at(5, 9)), [])
        for args in ((self.salon, self.client), (None, self.client)):
            text = export_lookup_csv(*args, now=NOW)
            self.assertEqual(
                text.strip().splitlines(), [",".join(EXPORT_FIELDNAMES)])
