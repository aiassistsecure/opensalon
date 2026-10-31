import csv
import datetime
import io

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.export_history import (
    EXPORT_FIELDNAMES,
    export_history,
    export_history_csv,
)
from onlinebooking.history import past_bookings
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def at(days, hour=10):
    return NOW + datetime.timedelta(days=days, hours=hour - 12)


class ExportHistoryTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Alice")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=60)

    def _appt(self, start, origin="online", status="booked", **kw):
        return Appointment.objects.create(
            client=kw.pop("client", self.client),
            staff_member=kw.pop("staff_member", self.staff),
            service=kw.pop("service", self.service),
            start=start, end=start + datetime.timedelta(hours=1),
            status=status, origin=origin, **kw)

    def test_only_online_origin_rows(self):
        online = self._appt(at(-1))
        for origin in ("phone", "walk_in", "unknown"):
            self._appt(at(-1, 11), origin=origin)
        rows = export_history(self.salon, self.client, now=NOW)
        self.assertEqual([r["id"] for r in rows], [online.pk])
        self.assertEqual(rows[0]["origin"], "online")

    def test_past_only_cancelled_included_and_boundary(self):
        self._appt(at(1))  # future: not history
        self._appt(NOW)  # exactly now: upcoming, not past
        cancelled = self._appt(at(-1), status="cancelled")
        kept = self._appt(at(-2), status="completed")
        rows = export_history(self.salon, self.client, now=NOW)
        self.assertEqual([r["id"] for r in rows], [cancelled.pk, kept.pk])
        self.assertEqual([r["is_cancelled"] for r in rows], [True, False])

    def test_values_match_service_newest_first(self):
        newest = self._appt(at(-1))
        self._appt(at(-2), origin="phone")  # service row, not exported
        oldest = self._appt(at(-3), service=None, service_name="Snap Cut")
        service_rows = [
            r for r in past_bookings(
                self.salon, self.client, now=NOW, limit=None)
            if r.appointment.origin == "online"
        ]
        rows = export_history(self.salon, self.client, now=NOW)
        self.assertEqual(
            [r["id"] for r in rows],
            [r.appointment.pk for r in service_rows])
        self.assertEqual([r["id"] for r in rows], [newest.pk, oldest.pk])
        self.assertEqual(list(rows[0].keys()), EXPORT_FIELDNAMES)
        first, last = rows
        svc = service_rows[0]
        self.assertEqual(first, {
            "id": newest.pk, "salon_id": self.salon.pk,
            "client_id": self.client.pk,
            "staff_member_id": self.staff.pk, "staff_name": "Alice",
            "service_id": self.service.pk, "service_name": svc.service_name,
            "start": svc.start.isoformat(), "end": svc.end.isoformat(),
            "status": "booked", "origin": "online", "is_cancelled": False})
        self.assertEqual(
            (last["service_id"], last["service_name"]), (None, "Snap Cut"))

    def test_csv_header_rows_and_empty_case(self):
        appt = self._appt(at(-1))
        text = export_history_csv(self.salon, self.client, now=NOW)
        parsed = list(csv.DictReader(io.StringIO(text)))
        header = list(csv.reader(io.StringIO(text)))[0]
        self.assertEqual(header, EXPORT_FIELDNAMES)
        self.assertEqual([int(r["id"]) for r in parsed], [appt.pk])
        self.assertEqual(parsed[0]["staff_name"], "Alice")
        self.assertEqual(parsed[0]["start"], appt.start.isoformat())
        # Empty: no bookings for a fresh client, and None scopes.
        fresh = Client.objects.create(
            salon=self.salon, first_name="No", last_name="Bookings")
        self.assertEqual(export_history(self.salon, fresh, now=NOW), [])
        self.assertEqual(export_history(None, self.client, now=NOW), [])
        empty = export_history_csv(self.salon, fresh, now=NOW)
        self.assertEqual(empty.strip().splitlines(),
                         [",".join(EXPORT_FIELDNAMES)])

    def test_salon_wide_when_no_client_and_read_only(self):
        mine = self._appt(at(-1))
        other_client = Client.objects.create(
            salon=self.salon, first_name="Two", last_name="Client")
        theirs = self._appt(at(-2), client=other_client)
        self._appt(at(-1, 11), origin="phone")
        before = Appointment.objects.count()
        rows = export_history(self.salon, now=NOW)
        self.assertEqual([r["id"] for r in rows], [mine.pk, theirs.pk])
        export_history_csv(self.salon, now=NOW)
        self.assertEqual(Appointment.objects.count(), before)
