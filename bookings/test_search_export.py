import csv
import datetime
import io

from django.test import TestCase

from bookings.models import Appointment
from bookings.search import search_appointments
from bookings.search_export import (
    SEARCH_EXPORT_FIELDNAMES,
    export_search_csv,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
DAY = datetime.date(2026, 11, 2)


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class SearchExportCsvTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two"
        )
        self.alice = Client.objects.create(
            salon=self.salon, first_name="Alice", last_name="Smith"
        )
        self.bob = Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Jones"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        self.early = self._appt(
            self.alice, self.staff2, at(DAY, 9),
            status=Appointment.Status.CONFIRMED,
            origin=Appointment.Origin.PHONE,
        )
        self.bob_appt = self._appt(
            self.bob, self.staff, at(DAY, 11),
            status=Appointment.Status.BOOKED,
            origin=Appointment.Origin.ONLINE,
        )
        self.snapshot = Appointment.objects.create(
            client=self.alice, staff_member=self.staff, service=None,
            service_name="Legacy Treatment",
            start=at(DAY, 16), end=at(DAY, 17),
            status=Appointment.Status.BOOKED,
        )
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Stylist One"
        )
        other_client = Client.objects.create(
            salon=self.other_salon, first_name="Alice", last_name="Smith"
        )
        self.foreign = Appointment.objects.create(
            client=other_client, staff_member=other_staff,
            service=self.service, start=at(DAY, 10), end=at(DAY, 11),
            status=Appointment.Status.BOOKED,
        )

    def _appt(self, client, staff, start, **kw):
        return Appointment.objects.create(
            client=client, staff_member=staff, service=self.service,
            start=start, end=start + datetime.timedelta(hours=1), **kw,
        )

    def test_header_and_row_content_for_filtered_search(self):
        text = export_search_csv(self.salon, query="alice")
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], SEARCH_EXPORT_FIELDNAMES)
        self.assertEqual(
            SEARCH_EXPORT_FIELDNAMES,
            ["id", "client", "staff", "service_name",
             "start", "end", "status", "origin"],
        )
        dict_rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(dict_rows, [
            {
                "id": str(self.early.pk),
                "client": "Alice Smith",
                "staff": "Stylist Two",
                "service_name": "Haircut",
                "start": at(DAY, 9).isoformat(),
                "end": at(DAY, 10).isoformat(),
                "status": "confirmed",
                "origin": "phone",
            },
            {
                "id": str(self.snapshot.pk),
                "client": "Alice Smith",
                "staff": "Stylist One",
                "service_name": "Legacy Treatment",
                "start": at(DAY, 16).isoformat(),
                "end": at(DAY, 17).isoformat(),
                "status": "booked",
                "origin": "unknown",
            },
        ])
        # Rows match the underlying search verbatim, in its order.
        self.assertEqual(
            [r["id"] for r in dict_rows],
            [str(a.pk) for a in search_appointments(self.salon, query="alice")],
        )

    def test_empty_result_is_header_only(self):
        text = export_search_csv(self.salon, query="no-such-client")
        self.assertEqual(
            list(csv.reader(io.StringIO(text))), [SEARCH_EXPORT_FIELDNAMES]
        )

    def test_salon_scoping_excludes_other_salon(self):
        rows = list(csv.DictReader(io.StringIO(export_search_csv(self.salon))))
        self.assertNotIn(str(self.foreign.pk), [r["id"] for r in rows])
        self.assertEqual(len(rows), 3)
        other_rows = list(csv.DictReader(io.StringIO(
            export_search_csv(self.other_salon)
        )))
        self.assertEqual([r["id"] for r in other_rows], [str(self.foreign.pk)])

    def test_filter_passthrough_status_narrows_rows(self):
        rows = list(csv.DictReader(io.StringIO(
            export_search_csv(self.salon, status="booked")
        )))
        self.assertEqual(
            [r["id"] for r in rows],
            [str(self.bob_appt.pk), str(self.snapshot.pk)],
        )
        self.assertTrue(all(r["status"] == "booked" for r in rows))
        staff_rows = list(csv.DictReader(io.StringIO(
            export_search_csv(self.salon, staff_member=self.staff2)
        )))
        self.assertEqual([r["id"] for r in staff_rows], [str(self.early.pk)])

    def test_read_only(self):
        before = Appointment.objects.count()
        export_search_csv(self.salon)
        self.assertEqual(Appointment.objects.count(), before)
