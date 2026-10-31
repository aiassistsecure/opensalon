import csv
import io
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from insights.popularity import service_popularity
from insights.popularity_export import (
    POPULARITY_FIELDNAMES,
    export_popularity_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)


class PopularityExportCsvTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="C", last_name="Test"
        )
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair"
        )
        self.cut = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        self.colour = Service.objects.create(
            category=category, name="Colour", service_minutes=90
        )

    def _appt(self, *, service=None, service_name="", day_offset=0,
              status=Appointment.Status.COMPLETED):
        start = datetime(2026, 11, 2, 10, 0, tzinfo=UTC) + timedelta(
            days=day_offset
        )
        return Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=service, service_name=service_name,
            start=start, end=start + timedelta(minutes=45),
            status=status,
        )

    def _rows(self, salon=None, start=START, end=END):
        text = export_popularity_csv(salon or self.salon, start, end)
        return list(csv.DictReader(io.StringIO(text)))

    def test_header(self):
        text = export_popularity_csv(self.salon, START, END)
        header = list(csv.reader(io.StringIO(text)))[0]
        self.assertEqual(header, POPULARITY_FIELDNAMES)
        self.assertEqual(POPULARITY_FIELDNAMES, [
            "service_id", "service_name", "completed_count",
            "booked_count", "cancelled_no_show_count",
            "cancelled_count", "no_show_count", "total_count",
        ])

    def test_rows_match_service_output(self):
        for i in range(3):
            self._appt(service=self.cut, day_offset=i)
        self._appt(service=self.cut, day_offset=3,
                   status=Appointment.Status.BOOKED)
        self._appt(service=self.cut, day_offset=4,
                   status=Appointment.Status.CANCELLED)
        self._appt(service=self.cut, day_offset=5,
                   status=Appointment.Status.NO_SHOW)
        self._appt(service=self.colour)
        rows = self._rows()
        service_rows = service_popularity(self.salon, START, END)
        self.assertEqual(len(rows), len(service_rows))
        for csv_row, svc in zip(rows, service_rows):
            self.assertEqual(csv_row, {
                "service_id": (
                    "" if svc.service_id is None else str(svc.service_id)
                ),
                "service_name": svc.service_name,
                "completed_count": str(svc.completed_count),
                "booked_count": str(svc.booked_count),
                "cancelled_no_show_count": str(
                    svc.cancelled_no_show_count
                ),
                "cancelled_count": str(svc.cancelled_count),
                "no_show_count": str(svc.no_show_count),
                "total_count": str(svc.total_count),
            })
        # Spot-check exact values and ordering from the service.
        self.assertEqual(rows[0]["service_name"], "Haircut")
        self.assertEqual(rows[0]["completed_count"], "3")
        self.assertEqual(rows[0]["total_count"], "6")

    def test_snapshot_row_has_empty_service_id(self):
        self._appt(service_name="Legacy Trim")
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["service_id"], "")
        self.assertEqual(rows[0]["service_name"], "Legacy Trim")

    def test_empty_is_header_only_and_read_only(self):
        text = export_popularity_csv(self.salon, START, END)
        self.assertEqual(
            list(csv.reader(io.StringIO(text))), [POPULARITY_FIELDNAMES]
        )
        self._appt(service=self.cut)
        before = Appointment.objects.count()
        export_popularity_csv(self.salon, START, END)
        self.assertEqual(Appointment.objects.count(), before)
