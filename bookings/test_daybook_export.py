import csv
import datetime
import io

from django.test import TestCase

from bookings.daybook import blocks_for_day
from bookings.daybook_export import (
    EXPORT_FIELDNAMES,
    export_daybook,
    export_daybook_csv,
)
from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class DaybookExportTests(TestCase):
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

    def _appt(self, start, end, staff=None, **kw):
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.staff,
            service=self.service, start=start, end=end, **kw,
        )

    def test_header_and_fieldnames(self):
        text = export_daybook_csv(self.salon, DAY)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], EXPORT_FIELDNAMES)
        self.assertEqual(
            EXPORT_FIELDNAMES,
            ["staff_member_id", "staff_name", "online_bookable",
             "appointment_id", "client_display_name", "service_name",
             "service_category_name", "start", "end", "status"],
        )

    def test_rows_match_service_output(self):
        other = StaffMember.objects.create(
            salon=self.salon, display_name="Another Stylist",
            online_bookable=False,
        )
        self._appt(at(DAY, 14), at(DAY, 15))
        self._appt(at(DAY, 9), at(DAY, 9, 45),
                   status=Appointment.Status.CONFIRMED)
        self._appt(at(DAY, 11), at(DAY, 12), staff=other)
        records = export_daybook(self.salon, DAY)
        expected = [
            {
                "staff_member_id": column.staff_member_id,
                "staff_name": column.display_name,
                "online_bookable": column.online_bookable,
                "appointment_id": block.appointment_id,
                "client_display_name": block.client_display_name,
                "service_name": block.service_name,
                "service_category_name": block.service_category_name,
                "start": block.start.isoformat(),
                "end": block.end.isoformat(),
                "status": block.status,
            }
            for column in blocks_for_day(self.salon, DAY)
            for block in column.blocks
        ]
        self.assertEqual(records, expected)
        self.assertEqual(list(records[0].keys()), EXPORT_FIELDNAMES)
        # Deterministic: columns by staff name, blocks by start.
        self.assertEqual(
            [(r["staff_name"], r["start"]) for r in records],
            [("Another Stylist", at(DAY, 11).isoformat()),
             ("Stylist One", at(DAY, 9).isoformat()),
             ("Stylist One", at(DAY, 14).isoformat())],
        )
        self.assertFalse(records[0]["online_bookable"])
        parsed = list(csv.DictReader(io.StringIO(
            export_daybook_csv(self.salon, DAY))))
        self.assertEqual(len(parsed), len(records))
        for row, record in zip(parsed, records):
            self.assertEqual(row, {
                k: ("" if v is None else str(v)) for k, v in record.items()
            })

    def test_cancelled_excluded_and_snapshot_service(self):
        self._appt(at(DAY, 9), at(DAY, 10),
                   status=Appointment.Status.CANCELLED)
        Appointment.objects.create(
            client=self.client, staff_member=self.staff, service=None,
            service_name="Legacy Treatment",
            start=at(DAY, 11), end=at(DAY, 12),
        )
        records = export_daybook(self.salon, DAY)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["service_name"], "Legacy Treatment")
        self.assertEqual(records[0]["service_category_name"], "")
        self.assertEqual(records[0]["client_display_name"], "Test Example")

    def test_empty_day_and_idle_staff_export_no_rows(self):
        StaffMember.objects.create(salon=self.salon, display_name="Idle")
        self.assertEqual(export_daybook(self.salon, DAY), [])
        self.assertEqual(export_daybook(None, DAY), [])
        text = export_daybook_csv(self.salon, DAY)
        self.assertEqual(
            text.strip().splitlines(), [",".join(EXPORT_FIELDNAMES)])

    def test_salon_isolation(self):
        other_salon = Salon.objects.create(name="Other Salon", timezone="UTC")
        other_staff = StaffMember.objects.create(
            salon=other_salon, display_name="Other Stylist")
        other_client = Client.objects.create(
            salon=other_salon, first_name="Other", last_name="Client")
        Appointment.objects.create(
            client=other_client, staff_member=other_staff,
            service=self.service, start=at(DAY, 9), end=at(DAY, 10))
        mine = self._appt(at(DAY, 11), at(DAY, 12))
        records = export_daybook(self.salon, DAY)
        self.assertEqual([r["appointment_id"] for r in records], [mine.pk])

    def test_read_only(self):
        self._appt(at(DAY, 9), at(DAY, 10))
        before = (Appointment.objects.count(), Client.objects.count(),
                  StaffMember.objects.count())
        export_daybook(self.salon, DAY)
        export_daybook_csv(self.salon, DAY)
        self.assertEqual(
            (Appointment.objects.count(), Client.objects.count(),
             StaffMember.objects.count()), before)
