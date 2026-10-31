import csv
import datetime
import io

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.cancellations import online_cancellation_summary
from onlinebooking.cancellations_export import (
    EXPORT_FIELDNAMES,
    export_cancellations,
    export_cancellations_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
D1 = datetime.date(2026, 11, 2)
D2 = datetime.date(2026, 11, 3)
D3 = datetime.date(2026, 11, 4)


def at(day, hour=10):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


class CancellationsExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Alice")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Beth")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=60)
        self.service2 = Service.objects.create(
            category=cat, name="Colour", service_minutes=60)

    def _appt(self, day=D1, staff=None, service="default", **kw):
        svc = self.service if service == "default" else service
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.staff,
            service=svc, start=at(day), end=at(day, 11),
            status="cancelled", origin="online", **kw)

    def test_csv_headers(self):
        self._appt(D1)
        text = export_cancellations_csv(self.salon, D1, D3)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], EXPORT_FIELDNAMES)
        records = export_cancellations(self.salon, D1, D3)
        self.assertTrue(records)
        self.assertEqual(list(records[0].keys()), EXPORT_FIELDNAMES)

    def test_rows_match_service_output(self):
        self._appt(D1)
        self._appt(D1, service=self.service2)
        self._appt(D2, staff=self.staff2)
        # Excluded by the service, so excluded here too.
        Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(D1, 12), end=at(D1, 13),
            status="cancelled", origin="phone")
        summary = online_cancellation_summary(self.salon, D1, D3)
        records = export_cancellations(self.salon, D1, D3)
        staff_rows = [r for r in records if r["section"] == "staff"]
        self.assertEqual(
            [(r["staff_member_id"], r["staff_name"], r["count"])
             for r in staff_rows],
            [(r.staff_member_id, r.staff_display_name, r.count)
             for r in summary.by_staff])
        service_rows = [r for r in records if r["section"] == "service"]
        self.assertEqual(
            [(r["service_id"], r["service_name"], r["count"])
             for r in service_rows],
            [(r.service_id, r.service_name, r.count) for r in summary.by_service])
        day_rows = [r for r in records if r["section"] == "day"]
        self.assertEqual(
            [(r["date"], r["count"]) for r in day_rows],
            [(r.date.isoformat(), r.count) for r in summary.by_day])
        for section_rows in (staff_rows, service_rows, day_rows):
            self.assertEqual(
                sum(r["count"] for r in section_rows), summary.total)
        self.assertTrue(all(
            r["salon_id"] == self.salon.pk
            and r["start_date"] == D1.isoformat()
            and r["end_date"] == D3.isoformat() for r in records))
        # CSV agrees with the dict export.
        parsed = list(csv.DictReader(io.StringIO(
            export_cancellations_csv(self.salon, D1, D3))))
        self.assertEqual(len(parsed), len(records))
        self.assertEqual(
            [(r["section"], r["count"]) for r in parsed],
            [(r["section"], str(r["count"])) for r in records])

    def test_empty_exports_header_only(self):
        self.assertEqual(export_cancellations(self.salon), [])
        self.assertEqual(export_cancellations(None, D1, D2), [])
        for salon, args in ((self.salon, ()), (None, (D1, D2))):
            text = export_cancellations_csv(salon, *args)
            self.assertEqual(
                text.strip().splitlines(), [",".join(EXPORT_FIELDNAMES)])

    def test_ranged_empty_carries_zero_filled_days(self):
        records = export_cancellations(self.salon, D1, D2)
        self.assertEqual(
            [(r["section"], r["date"], r["count"]) for r in records],
            [("day", D1.isoformat(), 0), ("day", D2.isoformat(), 0)])
