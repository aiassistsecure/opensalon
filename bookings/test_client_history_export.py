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


class ClientHistoryExportWindowTests(TestCase):
    """The optional start_date/end_date window on appointment start."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.level = StaffLevel.objects.create(salon=self.salon, name="Level 6")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            staff_level=self.level)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        self.other = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        self.old = self._appt(at(-10, 9))
        self.recent = self._appt(at(-1, 9))
        self.recent_late = self._appt(at(-1, 23))
        self.future = self._appt(at(3, 9))
        self.other_appt = self._appt(at(-1, 10), client=self.other)

    def _appt(self, start, client=None):
        return Appointment.objects.create(
            client=client or self.client, staff_member=self.staff,
            service=self.service, start=start,
            end=start + datetime.timedelta(minutes=45))

    def _ids(self, **kw):
        return [r["id"] for r in export_client_history(
            self.salon, self.client, **kw)]

    def test_no_window_is_previous_output(self):
        self.assertEqual(
            self._ids(), [self.future.pk, self.recent_late.pk,
                          self.recent.pk, self.old.pk])
        self.assertEqual(
            export_client_history_csv(self.salon, self.client),
            export_client_history_csv(
                self.salon, self.client, start_date=None, end_date=None))

    def test_both_bounds_inclusive_whole_days(self):
        day = datetime.date(2026, 11, 1)
        self.assertEqual(
            self._ids(start_date=day, end_date=day),
            [self.recent_late.pk, self.recent.pk])

    def test_start_bound_only_is_open_ended(self):
        self.assertEqual(
            self._ids(start_date=datetime.date(2026, 11, 2)),
            [self.future.pk])

    def test_end_bound_only_is_open_ended(self):
        self.assertEqual(
            self._ids(end_date=datetime.date(2026, 11, 1)),
            [self.recent_late.pk, self.recent.pk, self.old.pk])

    def test_window_composes_with_client_filter(self):
        day = datetime.date(2026, 11, 1)
        rows = export_client_history(
            self.salon, self.other, start_date=day, end_date=day)
        self.assertEqual([r["id"] for r in rows], [self.other_appt.pk])

    def test_window_composes_with_upcoming_only(self):
        rows = export_client_history(
            self.salon, self.client, upcoming_only=True, now=NOW,
            start_date=datetime.date(2026, 11, 1),
            end_date=datetime.date(2026, 11, 4))
        self.assertEqual(rows, [])
        rows = export_client_history(
            self.salon, self.client, upcoming_only=True, now=NOW,
            end_date=datetime.date(2026, 11, 30))
        self.assertEqual([r["id"] for r in rows], [self.future.pk])

    def test_reversed_window_is_empty(self):
        self.assertEqual(
            self._ids(start_date=datetime.date(2026, 11, 5),
                      end_date=datetime.date(2026, 11, 1)), [])
        self.assertEqual(
            export_client_history_csv(
                self.salon, self.client,
                start_date=datetime.date(2026, 11, 5),
                end_date=datetime.date(2026, 11, 1)),
            ",".join(CLIENT_HISTORY_EXPORT_FIELDNAMES) + "\n")

    def test_datetime_bounds_reduce_to_local_date(self):
        self.assertEqual(
            self._ids(start_date=at(-1, 18), end_date=at(-1, 18)),
            [self.recent_late.pk, self.recent.pk])

    def test_csv_twin_matches_windowed_rows(self):
        day = datetime.date(2026, 11, 1)
        text = export_client_history_csv(
            self.salon, self.client, start_date=day, end_date=day)
        csv_rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            [int(r["id"]) for r in csv_rows],
            [self.recent_late.pk, self.recent.pk])


class ClientHistoryExportStatusTests(TestCase):
    """The optional status filter on stored Appointment.Status."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.level = StaffLevel.objects.create(salon=self.salon, name="Level 6")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            staff_level=self.level)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        self.other = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        self.completed = self._appt(
            at(-10, 9), status=Appointment.Status.COMPLETED)
        self.booked = self._appt(at(-1, 9))
        self.cancelled = self._appt(
            at(-1, 10), status=Appointment.Status.CANCELLED)
        self.future_completed = self._appt(
            at(3, 9), status=Appointment.Status.COMPLETED)
        self.future = self._appt(at(4, 9))
        self.other_completed = self._appt(
            at(-1, 11), client=self.other,
            status=Appointment.Status.COMPLETED)

    def _appt(self, start, client=None, **kw):
        return Appointment.objects.create(
            client=client or self.client, staff_member=self.staff,
            service=self.service, start=start,
            end=start + datetime.timedelta(minutes=45), **kw)

    def _ids(self, **kw):
        return [r["id"] for r in export_client_history(
            self.salon, self.client, **kw)]

    def test_no_status_is_previous_output(self):
        self.assertEqual(
            self._ids(),
            [self.future.pk, self.future_completed.pk, self.cancelled.pk,
             self.booked.pk, self.completed.pk])
        self.assertEqual(
            export_client_history_csv(self.salon, self.client),
            export_client_history_csv(self.salon, self.client, status=None))

    def test_status_filter_only_exact_matching(self):
        rows = export_client_history(
            self.salon, self.client, status=Appointment.Status.COMPLETED)
        self.assertEqual(
            [r["id"] for r in rows],
            [self.future_completed.pk, self.completed.pk])
        self.assertTrue(all(r["status"] == "completed" for r in rows))
        self.assertEqual(
            self._ids(status="booked"), [self.future.pk, self.booked.pk])

    def test_status_composes_with_client_filter(self):
        rows = export_client_history(
            self.salon, self.other, status="completed")
        self.assertEqual([r["id"] for r in rows], [self.other_completed.pk])
        self.assertEqual(
            export_client_history(self.salon, self.other, status="booked"),
            [])

    def test_status_composes_with_upcoming_only(self):
        self.assertEqual(
            self._ids(upcoming_only=True, now=NOW, status="completed"),
            [self.future_completed.pk])
        self.assertEqual(
            self._ids(upcoming_only=True, now=NOW, status="booked"),
            [self.future.pk])

    def test_status_composes_with_window(self):
        day = datetime.date(2026, 11, 1)
        self.assertEqual(
            self._ids(start_date=day, end_date=day, status="cancelled"),
            [self.cancelled.pk])
        self.assertEqual(
            self._ids(start_date=day, end_date=day, status="completed"), [])

    def test_unknown_status_is_empty(self):
        self.assertEqual(self._ids(status="nope"), [])
        self.assertEqual(
            export_client_history_csv(self.salon, self.client, status="nope"),
            ",".join(CLIENT_HISTORY_EXPORT_FIELDNAMES) + "\n")

    def test_csv_twin_matches_status_rows(self):
        text = export_client_history_csv(
            self.salon, self.client, status="completed")
        csv_rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            [int(r["id"]) for r in csv_rows],
            [self.future_completed.pk, self.completed.pk])
        self.assertTrue(all(r["status"] == "completed" for r in csv_rows))


class ClientHistoryExportServiceFilterTests(TestCase):
    """The optional service filter on the appointment service FK."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.level = StaffLevel.objects.create(salon=self.salon, name="Level 6")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            staff_level=self.level)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        self.other = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        self.service2 = Service.objects.create(
            category=cat, name="Colour", service_minutes=60)
        self.cut_past = self._appt(at(-10, 9))
        self.colour = self._appt(
            at(-1, 9), service=self.service2,
            status=Appointment.Status.COMPLETED)
        self.cut = self._appt(at(-1, 10))
        self.colour_future = self._appt(at(3, 9), service=self.service2)
        self.snapshot = self._appt(at(4, 9), service=None)
        self.other_colour = self._appt(
            at(-1, 11), client=self.other, service=self.service2)

    def _appt(self, start, client=None, **kw):
        return Appointment.objects.create(
            client=client or self.client, staff_member=self.staff,
            service=kw.pop("service", self.service), start=start,
            end=start + datetime.timedelta(minutes=45), **kw)

    def _ids(self, **kw):
        return [r["id"] for r in export_client_history(
            self.salon, self.client, **kw)]

    def test_no_service_is_previous_output(self):
        self.assertEqual(
            self._ids(),
            [self.snapshot.pk, self.colour_future.pk, self.cut.pk,
             self.colour.pk, self.cut_past.pk])
        self.assertEqual(
            export_client_history_csv(self.salon, self.client),
            export_client_history_csv(self.salon, self.client, service=None))

    def test_service_filter_by_instance_and_pk(self):
        self.assertEqual(
            self._ids(service=self.service),
            [self.cut.pk, self.cut_past.pk])
        self.assertEqual(
            self._ids(service=self.service2.pk),
            [self.colour_future.pk, self.colour.pk])
        rows = export_client_history(
            self.salon, self.client, service=self.service2)
        self.assertTrue(
            all(r["service_id"] == self.service2.pk for r in rows))

    def test_service_composes_with_client_and_status(self):
        rows = export_client_history(
            self.salon, self.other, service=self.service2)
        self.assertEqual([r["id"] for r in rows], [self.other_colour.pk])
        self.assertEqual(
            self._ids(service=self.service2, status="completed"),
            [self.colour.pk])
        self.assertEqual(
            self._ids(service=self.service, status="completed"), [])

    def test_service_composes_with_upcoming_and_window(self):
        self.assertEqual(
            self._ids(upcoming_only=True, now=NOW, service=self.service2),
            [self.colour_future.pk])
        day = datetime.date(2026, 11, 1)
        self.assertEqual(
            self._ids(start_date=day, end_date=day, service=self.service2),
            [self.colour.pk])

    def test_other_salon_service_and_snapshot_are_empty(self):
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        cat = ServiceCategory.objects.create(salon=other_salon, name="Hair")
        outsider = Service.objects.create(
            category=cat, name="Other Cut", service_minutes=30)
        self.assertEqual(self._ids(service=outsider), [])
        self.assertEqual(
            export_client_history_csv(
                self.salon, self.client, service=outsider),
            ",".join(CLIENT_HISTORY_EXPORT_FIELDNAMES) + "\n")

    def test_csv_twin_matches_service_rows(self):
        text = export_client_history_csv(
            self.salon, self.client, service=self.service2)
        csv_rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            [int(r["id"]) for r in csv_rows],
            [self.colour_future.pk, self.colour.pk])
