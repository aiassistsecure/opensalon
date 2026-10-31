import csv
import datetime
import io

from django.test import TestCase

from bookings.models import Appointment
from bookings.status_counts import appointment_status_counts
from bookings.status_export import (
    STATUS_EXPORT_FIELDNAMES,
    export_status_counts_csv,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class StatusExportCsvTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )

    def _appt(self, start, status=Appointment.Status.BOOKED):
        return Appointment.objects.create(
            client=self.client, staff_member=self.staff, service=self.service,
            start=start, end=start + datetime.timedelta(minutes=45),
            status=status,
        )

    def test_header(self):
        text = export_status_counts_csv(self.salon, DAY)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], STATUS_EXPORT_FIELDNAMES)
        self.assertEqual(
            STATUS_EXPORT_FIELDNAMES,
            ["salon_id", "start_date", "end_date", "status", "count", "total"],
        )

    def test_row_values_match_service_output(self):
        self._appt(at(DAY, 9), Appointment.Status.BOOKED)
        self._appt(at(DAY, 10), Appointment.Status.BOOKED)
        self._appt(at(DAY, 11), Appointment.Status.COMPLETED)
        self._appt(at(DAY, 12), Appointment.Status.CANCELLED)
        last = DAY + datetime.timedelta(days=1)
        self._appt(at(last, 9), Appointment.Status.NO_SHOW)
        # Single day: rows match the service result verbatim.
        result = appointment_status_counts(self.salon, DAY)
        rows = list(csv.DictReader(io.StringIO(
            export_status_counts_csv(self.salon, DAY)
        )))
        self.assertEqual(
            [r["status"] for r in rows], list(result.by_status.keys())
        )
        for row in rows:
            self.assertEqual(row, {
                "salon_id": str(self.salon.pk),
                "start_date": result.start_date.isoformat(),
                "end_date": result.end_date.isoformat(),
                "status": row["status"],
                "count": str(result.by_status[row["status"]]),
                "total": str(result.total),
            })
        self.assertEqual(result.total, 4)
        # Range form passes through: the extra day is included.
        range_result = appointment_status_counts(self.salon, DAY, last)
        range_rows = list(csv.DictReader(io.StringIO(
            export_status_counts_csv(self.salon, DAY, last)
        )))
        self.assertTrue(all(r["total"] == str(range_result.total) for r in range_rows))
        self.assertEqual(range_result.total, 5)
        by_status = {r["status"]: r["count"] for r in range_rows}
        self.assertEqual(by_status["no_show"], str(range_result.no_show))

    def test_empty_day_is_zero_rows_matching_service(self):
        result = appointment_status_counts(self.salon, DAY)
        self.assertEqual(result.total, 0)
        rows = list(csv.DictReader(io.StringIO(
            export_status_counts_csv(self.salon, DAY)
        )))
        # The service zero-fills every status, so an empty day
        # exports one zero row per status — not a header alone.
        self.assertEqual(len(rows), len(result.by_status))
        for row in rows:
            self.assertEqual(row["count"], "0")
            self.assertEqual(row["total"], "0")
            self.assertEqual(row["start_date"], DAY.isoformat())
            self.assertEqual(row["end_date"], DAY.isoformat())

    def test_read_only(self):
        self._appt(at(DAY, 9))
        before = Appointment.objects.count()
        export_status_counts_csv(self.salon, DAY)
        self.assertEqual(Appointment.objects.count(), before)
