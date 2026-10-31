import csv
import datetime
import io

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.export_upcoming import (
    EXPORT_FIELDNAMES,
    export_upcoming,
    export_upcoming_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def at(days, hour=10):
    return NOW + datetime.timedelta(days=days, hours=hour - 12)


class ExportUpcomingTests(TestCase):
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

    def test_origin_filtering_excludes_non_online(self):
        online = self._appt(at(1))
        for origin in ("phone", "walk_in", "unknown"):
            self._appt(at(1, 11), origin=origin)
        rows = export_upcoming(self.salon, now=NOW)
        self.assertEqual([r["id"] for r in rows], [online.pk])
        self.assertEqual(rows[0]["origin"], "online")

    def test_window_past_cancelled_and_boundary(self):
        self._appt(NOW - datetime.timedelta(minutes=1))
        self._appt(at(1), status="cancelled")
        at_now = self._appt(NOW)
        future = self._appt(at(30))
        rows = export_upcoming(self.salon, now=NOW)
        self.assertEqual([r["id"] for r in rows], [at_now.pk, future.pk])
        # With a 7-day horizon the far appointment falls outside.
        windowed = export_upcoming(self.salon, now=NOW, days=7)
        self.assertEqual([r["id"] for r in windowed], [at_now.pk])
        self.assertEqual(export_upcoming(self.salon, now=NOW, days=0), [])
        # Default reference instant also works (all fixtures future/past
        # relative to real now are not relied on; explicit now above).

    def test_ordering_by_start_then_id_and_row_shape(self):
        later = self._appt(at(2))
        first = self._appt(at(1))
        same_start_second = self._appt(at(1))
        rows = export_upcoming(self.salon, now=NOW)
        self.assertEqual(
            [r["id"] for r in rows],
            [first.pk, same_start_second.pk, later.pk])
        self.assertEqual(list(rows[0].keys()), EXPORT_FIELDNAMES)
        self.assertEqual(rows[0], {
            "id": first.pk, "salon_id": self.salon.pk,
            "client_id": self.client.pk,
            "staff_member_id": self.staff.pk,
            "service_id": self.service.pk, "service_name": "Haircut",
            "start": first.start.isoformat(), "status": "booked",
            "origin": "online"})

    def test_salon_isolation(self):
        other = Salon.objects.create(name="Other", timezone="UTC")
        o_staff = StaffMember.objects.create(salon=other, display_name="O")
        o_client = Client.objects.create(
            salon=other, first_name="O", last_name="X")
        others = self._appt(at(1), staff_member=o_staff, client=o_client)
        self._appt(at(1), client=o_client)  # client elsewhere: excluded
        mine = self._appt(at(1))
        rows = export_upcoming(self.salon, now=NOW)
        self.assertEqual([r["id"] for r in rows], [mine.pk])
        other_rows = export_upcoming(other, now=NOW)
        self.assertEqual([r["id"] for r in other_rows], [others.pk])
        self.assertEqual(export_upcoming(None, now=NOW), [])

    def test_snapshot_service_name_and_csv_agrees(self):
        snap = self._appt(at(1), service=None, service_name="Snapshot Cut")
        live = self._appt(at(2))
        rows = export_upcoming(self.salon, now=NOW)
        self.assertEqual(
            [(r["service_id"], r["service_name"]) for r in rows],
            [(None, "Snapshot Cut"), (self.service.pk, "Haircut")])
        text = export_upcoming_csv(self.salon, now=NOW)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            [int(r["id"]) for r in parsed], [snap.pk, live.pk])
        self.assertEqual(parsed[0]["service_name"], "Snapshot Cut")
        self.assertEqual(parsed[0]["start"], rows[0]["start"])
        header = list(csv.reader(io.StringIO(text)))[0]
        self.assertEqual(header, EXPORT_FIELDNAMES)

    def test_empty_is_empty_list_and_header_only_csv(self):
        self.assertEqual(export_upcoming(self.salon, now=NOW), [])
        text = export_upcoming_csv(self.salon, now=NOW)
        self.assertEqual(text.strip().splitlines(),
                         [",".join(EXPORT_FIELDNAMES)])

    def test_read_only(self):
        self._appt(at(1))
        before = Appointment.objects.count()
        export_upcoming(self.salon, now=NOW)
        export_upcoming_csv(self.salon, now=NOW)
        self.assertEqual(Appointment.objects.count(), before)
