import csv
import io
import json
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from insights.future_export import (
    FUTURE_FIELDNAMES,
    export_future_appointments_value,
    export_future_appointments_value_csv,
    future_appointments_csv,
)
from insights.services import future_appointments_value
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import StaffMember

AS_OF = datetime(2026, 11, 2, 12, 0, tzinfo=ZoneInfo("UTC"))


class FutureExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 1"
        )
        other_level = StaffLevel.objects.create(
            salon=self.other, name="Level 1"
        )
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            staff_level=self.level,
        )
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other Stylist",
            staff_level=other_level,
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="C", last_name="Test"
        )
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair"
        )
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"),
        )

    def _appt(self, *, when=None, staff=None,
              status=Appointment.Status.BOOKED):
        start = when or (AS_OF + timedelta(days=1))
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.staff,
            service=self.service, start=start,
            end=start + timedelta(minutes=45), status=status,
        )

    def _csv_rows(self, salon=None, as_of=AS_OF):
        text = export_future_appointments_value_csv(
            salon or self.salon, as_of
        )
        return list(csv.DictReader(io.StringIO(text)))

    def test_header_and_fieldnames(self):
        text = export_future_appointments_value_csv(self.salon, AS_OF)
        header = list(csv.reader(io.StringIO(text)))[0]
        self.assertEqual(header, FUTURE_FIELDNAMES)
        self.assertEqual(FUTURE_FIELDNAMES, [
            "date", "value", "count", "total", "total_count",
            "as_of", "start_date", "end_date",
        ])

    def test_rows_match_service_output(self):
        self._appt(when=AS_OF + timedelta(hours=2))
        self._appt(when=AS_OF + timedelta(days=2))
        self._appt(when=AS_OF + timedelta(days=2, hours=3))
        # Beyond the 7-day breakdown: counts toward summary only.
        self._appt(when=AS_OF + timedelta(days=30))
        self._appt(status=Appointment.Status.CANCELLED)

        result = future_appointments_value(self.salon, AS_OF)
        rows = export_future_appointments_value(self.salon, AS_OF)
        self.assertEqual(len(rows), 7)
        self.assertEqual(len(rows), len(result.days))
        for row, entry in zip(rows, result.days):
            self.assertEqual(row, {
                "date": entry.day.isoformat(),
                "value": str(entry.value.quantize(Decimal("0.01"))),
                "count": entry.count,
                "total": str(result.total.quantize(Decimal("0.01"))),
                "total_count": result.count,
                "as_of": result.as_of.isoformat(),
                "start_date": result.start_date.isoformat(),
                "end_date": result.end_date.isoformat(),
            })
        # Concrete fixture expectations: 4 priced, 1 cancelled out.
        self.assertEqual(
            (rows[0]["value"], rows[0]["count"]), ("85.00", 1)
        )
        self.assertEqual(
            (rows[2]["value"], rows[2]["count"]), ("170.00", 2)
        )
        self.assertEqual(rows[0]["total"], "340.00")
        self.assertEqual(rows[0]["total_count"], 4)
        self.assertEqual(rows[0]["start_date"], "2026-11-02")
        self.assertEqual(rows[0]["end_date"], "2026-11-08")
        json.dumps(rows)

    def test_csv_built_from_same_list(self):
        self._appt()
        records = export_future_appointments_value(self.salon, AS_OF)
        csv_rows = self._csv_rows()
        self.assertEqual(csv_rows, [
            {k: str(v) for k, v in record.items()}
            for record in records
        ])

    def test_empty_returns_seven_zero_rows_with_zero_summary(self):
        rows = export_future_appointments_value(self.salon, AS_OF)
        self.assertEqual(len(rows), 7)
        for row in rows:
            self.assertEqual(row["value"], "0.00")
            self.assertEqual(row["count"], 0)
            self.assertEqual(row["total"], "0.00")
            self.assertEqual(row["total_count"], 0)
        self.assertEqual(len(self._csv_rows()), 7)

    def test_alias(self):
        self._appt()
        rows = list(csv.DictReader(io.StringIO(
            future_appointments_csv(self.salon, AS_OF)
        )))
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[1]["value"], "85.00")

    def test_salon_scoping_and_read_only(self):
        self._appt()
        self._appt(staff=self.other_staff)
        rows = export_future_appointments_value(self.salon, AS_OF)
        self.assertEqual(rows[0]["total"], "85.00")
        self.assertEqual(rows[0]["total_count"], 1)
        before = Appointment.objects.count()
        export_future_appointments_value_csv(self.salon, AS_OF)
        export_future_appointments_value(self.salon, AS_OF)
        self.assertEqual(Appointment.objects.count(), before)
