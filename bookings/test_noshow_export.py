import csv
import datetime
import io

from django.test import TestCase

from bookings.models import Appointment
from bookings.noshow import noshow_appointments
from bookings.noshow_export import (
    NOSHOW_EXPORT_FIELDNAMES,
    export_noshow_csv,
    noshow_csv,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class NoShowExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example",
            email="test@example.com", phone="555-0100")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)

    def _appt(self, start, status=Appointment.Status.NO_SHOW, **kw):
        return Appointment.objects.create(
            client=kw.pop("client", self.client),
            staff_member=kw.pop("staff_member", self.staff),
            service=kw.pop("service", self.service),
            start=start, end=start + datetime.timedelta(minutes=45),
            status=status, **kw)

    def _rows(self, text):
        return list(csv.DictReader(io.StringIO(text)))

    def test_header_and_columns(self):
        self._appt(at(DAY, 9))
        text = export_noshow_csv(self.salon, DAY, now=NOW)
        lines = text.splitlines()
        self.assertEqual(lines[0], ",".join(NOSHOW_EXPORT_FIELDNAMES))
        self.assertEqual(
            NOSHOW_EXPORT_FIELDNAMES,
            ["id", "client_id", "client_name", "staff_member_id",
             "staff_name", "service_id", "service_name", "start",
             "end", "status"])
        self.assertTrue(text.endswith("\n"))
        self.assertNotIn("email", lines[0])
        self.assertNotIn("phone", lines[0])

    def test_rows_match_service_output(self):
        a = self._appt(at(DAY, 9))
        b = self._appt(at(DAY, 14), service=None,
                       service_name="Imported Cut")
        self._appt(at(DAY, 15), Appointment.Status.COMPLETED)
        self._appt(at(DAY, 16), Appointment.Status.CANCELLED)
        service_rows = noshow_appointments(self.salon, DAY, now=NOW)
        rows = self._rows(export_noshow_csv(self.salon, DAY, now=NOW))
        self.assertEqual([r["id"] for r in rows],
                         [str(b.pk), str(a.pk)])
        self.assertEqual(len(rows), len(service_rows))
        for csv_row, svc in zip(rows, service_rows):
            for name in NOSHOW_EXPORT_FIELDNAMES:
                expected = "" if svc[name] is None else str(svc[name])
                self.assertEqual(csv_row[name], expected, name)
        self.assertEqual(rows[0]["service_name"], "Imported Cut")
        self.assertEqual(rows[0]["service_id"], "")
        self.assertEqual(rows[0]["status"], "no_show")
        self.assertNotIn("test@example.com", str(rows))
        self.assertNotIn("555-0100", str(rows))

    def test_salon_isolation(self):
        self._appt(at(DAY, 9))
        other = Salon.objects.create(name="Other", timezone="UTC")
        os_ = StaffMember.objects.create(salon=other, display_name="Other")
        oc = Client.objects.create(salon=other, first_name="O", last_name="C")
        self._appt(at(DAY, 10), client=oc, staff_member=os_)
        rows = self._rows(export_noshow_csv(self.salon, DAY, now=NOW))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["client_name"], "Test Example")
        other_rows = self._rows(export_noshow_csv(other, DAY, now=NOW))
        self.assertEqual(len(other_rows), 1)
        self.assertEqual(other_rows[0]["client_name"], "O C")

    def test_empty_result_is_header_only(self):
        text = export_noshow_csv(self.salon, DAY, now=NOW)
        self.assertEqual(
            text, ",".join(NOSHOW_EXPORT_FIELDNAMES) + "\n")
        self.assertEqual(self._rows(text), [])
        # Alias behaves identically; a day with only non-no-shows too.
        self._appt(at(DAY, 9), Appointment.Status.COMPLETED)
        self.assertEqual(
            noshow_csv(self.salon, DAY, now=NOW),
            ",".join(NOSHOW_EXPORT_FIELDNAMES) + "\n")
