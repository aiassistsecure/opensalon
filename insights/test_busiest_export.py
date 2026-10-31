import csv
import io
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from bookings.models import Appointment
from checkout.models import Sale, SaleItem
from clients.models import Client
from insights.busiest_export import (
    BUSIEST_FIELDNAMES,
    export_busiest_days,
    export_busiest_days_csv,
)
from insights.services import busiest_days
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import StaffMember

SINCE = date(2026, 11, 2)
UNTIL = date(2026, 11, 8)


class BusiestExportTests(TestCase):
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

    def _appt(self, *, day_offset=0, hour=10, staff=None,
              status=Appointment.Status.BOOKED):
        start = datetime(
            2026, 11, 2 + day_offset, hour, 0, tzinfo=ZoneInfo("UTC")
        )
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.staff,
            service=self.service, start=start,
            end=start + timedelta(minutes=45), status=status,
        )

    def _sale(self, *, day_offset=0, salon=None, price="50.00"):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED
        )
        stamp = datetime(
            2026, 11, 2 + day_offset, 12, 0, tzinfo=ZoneInfo("UTC")
        )
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp
        )
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal(price),
        )
        return sale

    def _csv_rows(self, salon=None, since=SINCE, until=UNTIL):
        text = export_busiest_days_csv(salon or self.salon, since, until)
        return list(csv.DictReader(io.StringIO(text)))

    def test_header_and_fieldnames(self):
        text = export_busiest_days_csv(self.salon, SINCE, UNTIL)
        header = list(csv.reader(io.StringIO(text)))[0]
        self.assertEqual(header, BUSIEST_FIELDNAMES)
        self.assertEqual(BUSIEST_FIELDNAMES, [
            "weekday", "weekday_name", "count", "revenue",
            "appointment_value",
        ])

    def test_rows_match_service_output_and_ordering(self):
        self._appt(day_offset=5)
        self._appt(day_offset=5, hour=12)
        self._appt(day_offset=0)
        self._appt(day_offset=1, status=Appointment.Status.CANCELLED)
        self._sale(day_offset=5, price="133.00")
        rows = export_busiest_days(self.salon, SINCE, UNTIL)
        service_rows = busiest_days(self.salon, SINCE, UNTIL)
        self.assertEqual(len(rows), 7)
        self.assertEqual(len(rows), len(service_rows))
        for row, svc in zip(rows, service_rows):
            self.assertEqual(row, {
                "weekday": svc.weekday,
                "weekday_name": svc.weekday_name,
                "count": svc.count,
                "revenue": str(svc.revenue.quantize(Decimal("0.01"))),
                "appointment_value": str(
                    svc.appointment_value.quantize(Decimal("0.01"))
                ),
            })
        self.assertEqual(rows[0]["weekday"], 5)
        self.assertEqual(rows[0]["weekday_name"], "Saturday")
        self.assertEqual(rows[0]["count"], 2)
        self.assertEqual(rows[0]["appointment_value"], "170.00")
        self.assertEqual(rows[0]["revenue"], "133.00")
        json.dumps(rows)

    def test_csv_built_from_same_list(self):
        self._appt(day_offset=0)
        records = export_busiest_days(self.salon, SINCE, UNTIL)
        csv_rows = self._csv_rows()
        self.assertEqual(csv_rows, [
            {k: str(v) for k, v in record.items()} for record in records
        ])

    def test_empty_and_reversed_return_seven_zero_rows(self):
        for rows in (
            export_busiest_days(self.salon, SINCE, UNTIL),
            export_busiest_days(self.salon, UNTIL, SINCE),
        ):
            self.assertEqual(len(rows), 7)
            self.assertEqual([r["weekday"] for r in rows], list(range(7)))
            for row in rows:
                self.assertEqual(row["count"], 0)
                self.assertEqual(row["revenue"], "0.00")
                self.assertEqual(row["appointment_value"], "0.00")

    def test_salon_scoping_and_read_only(self):
        self._appt(day_offset=0)
        self._appt(day_offset=0, hour=16, staff=self.other_staff)
        self._sale(day_offset=0, salon=self.other, price="999.00")
        rows = export_busiest_days(self.salon, SINCE, UNTIL)
        monday = [r for r in rows if r["weekday"] == 0][0]
        self.assertEqual(monday["count"], 1)
        self.assertEqual(monday["revenue"], "0.00")
        before = (Appointment.objects.count(), Sale.objects.count())
        export_busiest_days_csv(self.salon, SINCE, UNTIL)
        export_busiest_days(self.salon, SINCE, UNTIL)
        self.assertEqual(
            (Appointment.objects.count(), Sale.objects.count()), before
        )
