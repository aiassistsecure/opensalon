import csv
import datetime
import io
import json
from decimal import Decimal

from django.test import TestCase

from bookings.client_history import client_appointments
from bookings.client_history_export import (
    CLIENT_HISTORY_EXPORT_FIELDNAMES,
    client_history_csv,
    export_client_history,
    export_client_history_csv,
)
from bookings.models import Appointment, AppointmentNote
from clients.models import Client, ClientNote
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def at(day_offset, hour, minute=0):
    return NOW + datetime.timedelta(days=day_offset, hours=hour - 12, minutes=minute)


class ClientHistoryExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.level = StaffLevel.objects.create(salon=self.salon, name="Level 6")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            staff_level=self.level)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example",
            email="test@example.com", phone="555-0100")
        self.other = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"))

    def _appt(self, start, client=None, **kw):
        return Appointment.objects.create(
            client=client or self.client,
            staff_member=kw.pop("staff_member", self.staff),
            service=kw.pop("service", self.service),
            start=start, end=start + datetime.timedelta(minutes=45), **kw)

    def _rows(self, text):
        return list(csv.DictReader(io.StringIO(text)))

    def test_header_keys_and_json_serializable(self):
        appt = self._appt(at(-1, 9), status=Appointment.Status.COMPLETED)
        rows = export_client_history(self.salon, self.client)
        self.assertEqual(len(rows), 1)
        self.assertEqual(list(rows[0].keys()), CLIENT_HISTORY_EXPORT_FIELDNAMES)
        self.assertEqual(rows[0]["id"], appt.pk)
        self.assertEqual(rows[0]["salon_id"], self.salon.pk)
        self.assertEqual(rows[0]["client_id"], self.client.pk)
        self.assertEqual(rows[0]["client_name"], "Test Example")
        self.assertEqual(rows[0]["staff_name"], "Stylist One")
        self.assertEqual(rows[0]["service_name"], "Haircut")
        self.assertEqual(rows[0]["start"], at(-1, 9).isoformat())
        self.assertEqual(rows[0]["price"], "85.00")
        self.assertIsInstance(rows[0]["price"], str)
        json.dumps(rows)  # must not raise

    def test_ordering_and_rows_match_service(self):
        old = self._appt(at(-10, 9))
        recent = self._appt(at(-1, 9))
        future = self._appt(at(3, 9))
        service_ids = [a.pk for a in client_appointments(self.client)]
        rows = export_client_history(self.salon, self.client)
        self.assertEqual([r["id"] for r in rows], service_ids)
        self.assertEqual([r["id"] for r in rows],
                         [future.pk, recent.pk, old.pk])
        upcoming = export_client_history(
            self.salon, self.client, upcoming_only=True, now=NOW)
        self.assertEqual([r["id"] for r in upcoming], [future.pk])

    def test_csv_built_from_same_rows(self):
        self._appt(at(-1, 9))
        self._appt(at(-2, 9), service=None, service_name="Imported Cut")
        text = export_client_history_csv(self.salon, self.client)
        self.assertEqual(text.splitlines()[0],
                         ",".join(CLIENT_HISTORY_EXPORT_FIELDNAMES))
        self.assertTrue(text.endswith("\n"))
        csv_rows = self._rows(text)
        dict_rows = export_client_history(self.salon, self.client)
        self.assertEqual(len(csv_rows), len(dict_rows))
        for csv_row, row in zip(csv_rows, dict_rows):
            for name in CLIENT_HISTORY_EXPORT_FIELDNAMES:
                expected = "" if row[name] is None else str(row[name])
                self.assertEqual(csv_row[name], expected, name)
        self.assertEqual(csv_rows[1]["service_name"], "Imported Cut")
        self.assertEqual(csv_rows[1]["service_id"], "")
        self.assertEqual(csv_rows[1]["price"], "")
        self.assertEqual(
            client_history_csv(self.salon, self.client), text)

    def test_salon_and_client_isolation(self):
        self._appt(at(-1, 9))
        self._appt(at(-1, 10), client=self.other)
        rows = export_client_history(self.salon, self.client)
        self.assertEqual(len(rows), 1)
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        self.assertEqual(export_client_history(other_salon, self.client), [])
        self.assertEqual(
            export_client_history_csv(other_salon, self.client),
            ",".join(CLIENT_HISTORY_EXPORT_FIELDNAMES) + "\n")
        self.assertEqual(export_client_history(None, None), [])

    def test_empty_is_empty_list_and_header_only(self):
        self.assertEqual(export_client_history(self.salon, self.client), [])
        self.assertEqual(
            export_client_history_csv(self.salon, self.client),
            ",".join(CLIENT_HISTORY_EXPORT_FIELDNAMES) + "\n")

    def test_no_notes_or_contact_details_exported(self):
        appt = self._appt(at(-1, 9))
        AppointmentNote.objects.create(
            appointment=appt, body="appointment secret note")
        ClientNote.objects.create(
            client=self.client, body="record secret note")
        rows = export_client_history(self.salon, self.client)
        text = export_client_history_csv(self.salon, self.client)
        for blob in (str(rows), text):
            self.assertNotIn("secret note", blob)
            self.assertNotIn("test@example.com", blob)
            self.assertNotIn("555-0100", blob)
        self.assertNotIn("note", CLIENT_HISTORY_EXPORT_FIELDNAMES)
