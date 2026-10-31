import csv
import datetime
import io

from django.test import TestCase

from bookings.models import Appointment
from bookings.upcoming_export import UPCOMING_FIELDNAMES, export_upcoming_csv
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class UpcomingExportCsvTests(TestCase):
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
        self.start = at(DAY, 0)

    def _appt(self, start, **kw):
        end = kw.pop("end", start + datetime.timedelta(minutes=45))
        return Appointment.objects.create(
            client=kw.pop("client", self.client),
            staff_member=kw.pop("staff_member", self.staff),
            service=kw.pop("service", self.service),
            start=start, end=end, **kw,
        )

    def _rows(self, salon=None, **kw):
        text = export_upcoming_csv(salon or self.salon, self.start, **kw)
        return list(csv.DictReader(io.StringIO(text)))

    def test_header_only_when_empty(self):
        text = export_upcoming_csv(self.salon, self.start, days=7)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows, [UPCOMING_FIELDNAMES])
        self.assertEqual(
            UPCOMING_FIELDNAMES,
            ["id", "salon_id", "client_id", "client_name",
             "staff_member_id", "staff_name", "service_name",
             "start", "end", "status", "origin"],
        )

    def test_row_content_and_service_ordering(self):
        late = self._appt(at(DAY, 14), origin=Appointment.Origin.PHONE)
        early = self._appt(at(DAY, 9), origin=Appointment.Origin.ONLINE)
        rows = self._rows(days=7)
        # Service ordering: by start, then pk — not creation order.
        self.assertEqual([int(r["id"]) for r in rows], [early.pk, late.pk])
        self.assertEqual(rows[0], {
            "id": str(early.pk),
            "salon_id": str(self.salon.pk),
            "client_id": str(self.client.pk),
            "client_name": "Test Example",
            "staff_member_id": str(self.staff.pk),
            "staff_name": "Stylist One",
            "service_name": "Haircut",
            "start": at(DAY, 9).isoformat(),
            "end": at(DAY, 9, 45).isoformat(),
            "status": Appointment.Status.BOOKED,
            "origin": Appointment.Origin.ONLINE,
        })
        self.assertEqual(rows[1]["origin"], Appointment.Origin.PHONE)

    def test_snapshot_service_name_when_no_service(self):
        self._appt(at(DAY, 9), service=None, service_name="Imported Cut")
        (row,) = self._rows(days=1)
        self.assertEqual(row["service_name"], "Imported Cut")

    def test_cancelled_and_past_excluded_per_service_definition(self):
        self._appt(at(DAY, 9), status=Appointment.Status.CANCELLED)
        self._appt(self.start - datetime.timedelta(hours=1))  # past
        self._appt(self.start + datetime.timedelta(days=7))  # at horizon end
        kept = self._appt(at(DAY, 10), status=Appointment.Status.CONFIRMED)
        rows = self._rows(days=7)
        self.assertEqual([int(r["id"]) for r in rows], [kept.pk])
        self.assertEqual(rows[0]["status"], Appointment.Status.CONFIRMED)

    def test_salon_isolation(self):
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        other_staff = StaffMember.objects.create(
            salon=other_salon, display_name="Other Stylist"
        )
        other_client = Client.objects.create(
            salon=other_salon, first_name="Other", last_name="Client"
        )
        mine = self._appt(at(DAY, 9))
        self._appt(at(DAY, 10), client=other_client, staff_member=other_staff)
        rows = self._rows(days=1)
        self.assertEqual([int(r["id"]) for r in rows], [mine.pk])
        self.assertEqual(rows[0]["salon_id"], str(self.salon.pk))
        other_rows = self._rows(salon=other_salon, days=1)
        self.assertEqual(len(other_rows), 1)
        self.assertEqual(other_rows[0]["salon_id"], str(other_salon.pk))

    def test_read_only(self):
        self._appt(at(DAY, 9))
        before = Appointment.objects.count()
        export_upcoming_csv(self.salon, self.start, days=7)
        self.assertEqual(Appointment.objects.count(), before)
