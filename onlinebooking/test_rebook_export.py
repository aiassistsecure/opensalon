import csv
import datetime
import io

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.rebook_export import (
    EXPORT_FIELDNAMES,
    export_rebook,
    export_rebook_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
DAY = datetime.date(2026, 10, 26)  # a Monday


def at(hour, minute=0):
    return datetime.datetime.combine(
        DAY, datetime.time(hour, minute), tzinfo=UTC)


class RebookExportTests(TestCase):
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

    def _appt(self, start, client=None, staff=None, service="svc", **kw):
        kw.setdefault("status", Appointment.Status.COMPLETED)
        return Appointment.objects.create(
            client=client or self.client,
            staff_member=staff or self.staff,
            service=self.service if service == "svc" else service,
            start=start,
            end=start + datetime.timedelta(minutes=45),
            **kw,
        )

    def test_csv_header_and_rows_match_rebook_service_rules(self):
        # Eligible per onlinebooking.rebook: not cancelled, has a
        # service. Any other status exports; no time filter.
        sooner = self._appt(at(9))
        later = self._appt(at(11), status=Appointment.Status.BOOKED)
        future = self._appt(
            at(13) + datetime.timedelta(days=30),
            status=Appointment.Status.CONFIRMED)
        self._appt(at(10), status=Appointment.Status.CANCELLED)
        self._appt(at(12), service=None, service_name="Snapshot Cut")
        text = export_rebook_csv(self.salon, self.client)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            [int(r["id"]) for r in parsed], [sooner.pk, later.pk, future.pk])
        row = parsed[0]
        self.assertEqual(row["salon_id"], str(self.salon.pk))
        self.assertEqual(row["client_id"], str(self.client.pk))
        self.assertEqual(row["staff_member_id"], str(self.staff.pk))
        self.assertEqual(row["staff_name"], "Online Stylist")
        self.assertEqual(row["service_id"], str(self.service.pk))
        self.assertEqual(row["service_name"], "Haircut")
        self.assertEqual(row["start"], sooner.start.isoformat())
        self.assertEqual(row["end"], sooner.end.isoformat())
        self.assertEqual(row["status"], Appointment.Status.COMPLETED)
        self.assertEqual(row["origin"], Appointment.Origin.UNKNOWN)
        records = export_rebook(self.salon, self.client)
        self.assertEqual(list(records[0].keys()), EXPORT_FIELDNAMES)
        self.assertEqual(
            [r["id"] for r in records], [sooner.pk, later.pk, future.pk])
        # Read-only: exporting created nothing.
        self.assertEqual(Appointment.objects.count(), 5)

    def test_deterministic_ordering_start_then_pk(self):
        second = self._appt(at(10))
        first = self._appt(at(9))
        same_start = self._appt(at(10))
        records = export_rebook(self.salon)
        self.assertEqual(
            [r["id"] for r in records],
            [first.pk, second.pk, same_start.pk])

    def test_per_client_scope_and_salon_wide(self):
        mine = self._appt(at(10))
        theirs = self._appt(at(9), client=self.other_client)
        self.assertEqual(
            [r["id"] for r in export_rebook(self.salon, self.client)],
            [mine.pk])
        self.assertEqual(
            [r["id"] for r in export_rebook(self.salon)],
            [theirs.pk, mine.pk])

    def test_salon_isolation(self):
        outsider = Client.objects.create(
            salon=self.other_salon, first_name="Out", last_name="Sider")
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Other Stylist")
        other_cat = ServiceCategory.objects.create(
            salon=self.other_salon, name="Hair")
        other_service = Service.objects.create(
            category=other_cat, name="Other Cut", service_minutes=30)
        self._appt(at(9), client=outsider, staff=other_staff,
                   service=other_service)
        mine = self._appt(at(10))
        self.assertEqual(export_rebook(self.salon, outsider), [])
        self.assertEqual(export_rebook(self.other_salon, self.client), [])
        self.assertEqual(
            [r["id"] for r in export_rebook(self.salon, self.client)],
            [mine.pk])
        self.assertEqual(
            [r["id"] for r in export_rebook(self.salon)], [mine.pk])

    def test_empty_exports_header_only(self):
        self._appt(at(9), status=Appointment.Status.CANCELLED)
        self.assertEqual(export_rebook(self.salon, self.client), [])
        self.assertEqual(export_rebook(None, self.client), [])
        self.assertEqual(export_rebook(self.salon, None), [
            r for r in export_rebook(self.salon, self.client)])
        for args in ((self.salon, self.client), (None, self.client)):
            text = export_rebook_csv(*args)
            self.assertEqual(
                text.strip().splitlines(), [",".join(EXPORT_FIELDNAMES)])
