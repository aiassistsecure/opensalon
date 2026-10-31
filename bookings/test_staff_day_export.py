import csv
import datetime
import io

from django.test import TestCase

from bookings.models import Appointment
from bookings.staff_day import staff_day_load
from bookings.staff_day_export import STAFF_DAY_FIELDNAMES, export_staff_day_csv
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class StaffDayExportCsvTests(TestCase):
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

    def test_header(self):
        text = export_staff_day_csv(self.salon, DAY)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], STAFF_DAY_FIELDNAMES)
        self.assertEqual(
            STAFF_DAY_FIELDNAMES,
            ["staff_member_id", "staff_name", "appointment_count",
             "booked_minutes", "first_start", "last_start", "last_end"],
        )

    def test_rows_match_service_output(self):
        other = StaffMember.objects.create(
            salon=self.salon, display_name="Another Stylist"
        )
        self._appt(at(DAY, 14), at(DAY, 15))
        self._appt(at(DAY, 9), at(DAY, 9, 45))
        self._appt(at(DAY, 11), at(DAY, 12, 30), staff=other)
        self._appt(at(DAY, 16), at(DAY, 17), status=Appointment.Status.CANCELLED)
        rows = list(csv.DictReader(io.StringIO(
            export_staff_day_csv(self.salon, DAY)
        )))
        loads = staff_day_load(self.salon, DAY)
        self.assertEqual(len(rows), len(loads))
        for row, load in zip(rows, loads):
            self.assertEqual(row, {
                "staff_member_id": str(load.staff_member_id),
                "staff_name": load.display_name,
                "appointment_count": str(load.appointment_count),
                "booked_minutes": str(load.booked_minutes),
                "first_start": load.first_start.isoformat() if load.first_start else "",
                "last_start": load.last_start.isoformat() if load.last_start else "",
                "last_end": load.last_end.isoformat() if load.last_end else "",
            })

    def test_salon_isolation(self):
        other_salon = Salon.objects.create(name="Other Salon", timezone="UTC")
        other_staff = StaffMember.objects.create(
            salon=other_salon, display_name="Other Stylist"
        )
        other_client = Client.objects.create(
            salon=other_salon, first_name="Other", last_name="Client"
        )
        Appointment.objects.create(
            client=other_client, staff_member=other_staff,
            service=self.service, start=at(DAY, 9), end=at(DAY, 10),
        )
        self._appt(at(DAY, 11), at(DAY, 12))
        rows = list(csv.DictReader(io.StringIO(
            export_staff_day_csv(self.salon, DAY)
        )))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["staff_member_id"], str(self.staff.pk))
        self.assertEqual(rows[0]["appointment_count"], "1")
        other_rows = list(csv.DictReader(io.StringIO(
            export_staff_day_csv(other_salon, DAY)
        )))
        self.assertEqual(len(other_rows), 1)
        self.assertEqual(other_rows[0]["staff_member_id"], str(other_staff.pk))

    def test_empty_day(self):
        rows = list(csv.DictReader(io.StringIO(
            export_staff_day_csv(self.salon, DAY)
        )))
        self.assertEqual(rows, [{
            "staff_member_id": str(self.staff.pk),
            "staff_name": "Stylist One",
            "appointment_count": "0",
            "booked_minutes": "0",
            "first_start": "",
            "last_start": "",
            "last_end": "",
        }])
        text = export_staff_day_csv(DAY)
        self.assertEqual(
            list(csv.reader(io.StringIO(text))), [STAFF_DAY_FIELDNAMES]
        )

    def test_read_only(self):
        self._appt(at(DAY, 9), at(DAY, 10))
        before = Appointment.objects.count()
        export_staff_day_csv(self.salon, DAY)
        self.assertEqual(Appointment.objects.count(), before)
