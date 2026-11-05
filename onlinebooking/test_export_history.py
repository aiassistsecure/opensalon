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


class ExportHistoryWindowTests(TestCase):
    """The optional start_date/end_date window on booking start."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Alice")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        self.other = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=60)
        self.old = self._appt(at(-10, 9))
        self.recent = self._appt(at(-1, 9))
        self.recent_late = self._appt(at(-1, 23))
        self.other_appt = self._appt(at(-1, 10), client=self.other)

    def _appt(self, start, client=None):
        return Appointment.objects.create(
            client=client or self.client, staff_member=self.staff,
            service=self.service, start=start,
            end=start + datetime.timedelta(hours=1),
            status="booked", origin="online")

    def _ids(self, **kw):
        return [r["id"] for r in export_history(
            self.salon, self.client, now=NOW, **kw)]

    def test_no_window_is_previous_output(self):
        self.assertEqual(
            self._ids(), [self.recent_late.pk, self.recent.pk, self.old.pk])
        self.assertEqual(
            export_history_csv(self.salon, self.client, now=NOW),
            export_history_csv(
                self.salon, self.client, now=NOW,
                start_date=None, end_date=None))

    def test_both_bounds_inclusive_whole_days(self):
        day = datetime.date(2026, 11, 1)
        self.assertEqual(
            self._ids(start_date=day, end_date=day),
            [self.recent_late.pk, self.recent.pk])

    def test_start_bound_only_is_open_ended(self):
        self.assertEqual(
            self._ids(start_date=datetime.date(2026, 11, 1)),
            [self.recent_late.pk, self.recent.pk])

    def test_end_bound_only_is_open_ended(self):
        self.assertEqual(
            self._ids(end_date=datetime.date(2026, 10, 23)),
            [self.old.pk])

    def test_window_composes_with_client_and_salon_wide(self):
        day = datetime.date(2026, 11, 1)
        rows = export_history(
            self.salon, self.other, now=NOW, start_date=day, end_date=day)
        self.assertEqual([r["id"] for r in rows], [self.other_appt.pk])
        rows = export_history(
            self.salon, now=NOW, start_date=day, end_date=day)
        self.assertEqual(
            [r["id"] for r in rows],
            [self.recent_late.pk, self.other_appt.pk, self.recent.pk])

    def test_window_applies_before_limit(self):
        day = datetime.date(2026, 10, 23)
        self.assertEqual(
            self._ids(limit=1, start_date=day, end_date=day),
            [self.old.pk])

    def test_reversed_window_is_empty(self):
        self.assertEqual(
            self._ids(start_date=datetime.date(2026, 11, 5),
                      end_date=datetime.date(2026, 11, 1)), [])
        self.assertEqual(
            export_history_csv(
                self.salon, self.client, now=NOW,
                start_date=datetime.date(2026, 11, 5),
                end_date=datetime.date(2026, 11, 1)),
            ",".join(EXPORT_FIELDNAMES) + "\n")

    def test_datetime_bounds_reduce_to_local_date(self):
        self.assertEqual(
            self._ids(start_date=at(-1, 18), end_date=at(-1, 18)),
            [self.recent_late.pk, self.recent.pk])

    def test_csv_twin_matches_windowed_rows(self):
        day = datetime.date(2026, 11, 1)
        text = export_history_csv(
            self.salon, self.client, now=NOW, start_date=day, end_date=day)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            [int(r["id"]) for r in parsed],
            [self.recent_late.pk, self.recent.pk])


class ExportHistoryStatusTests(TestCase):
    """The optional status filter on the booking's stored status."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Alice")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        self.other = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=60)
        self.booked = self._appt(at(-1, 9), status="booked")
        self.cancelled = self._appt(at(-2, 9), status="cancelled")
        self.completed = self._appt(at(-3, 9), status="completed")
        self.other_cancelled = self._appt(
            at(-1, 10), client=self.other, status="cancelled")

    def _appt(self, start, client=None, status="booked"):
        return Appointment.objects.create(
            client=client or self.client, staff_member=self.staff,
            service=self.service, start=start,
            end=start + datetime.timedelta(hours=1),
            status=status, origin="online")

    def _ids(self, **kw):
        return [r["id"] for r in export_history(
            self.salon, self.client, now=NOW, **kw)]

    def test_no_status_is_previous_output(self):
        self.assertEqual(
            self._ids(),
            [self.booked.pk, self.cancelled.pk, self.completed.pk])
        self.assertEqual(
            export_history_csv(self.salon, self.client, now=NOW),
            export_history_csv(
                self.salon, self.client, now=NOW, status=None))

    def test_status_filters_exactly(self):
        self.assertEqual(self._ids(status="cancelled"), [self.cancelled.pk])
        self.assertEqual(self._ids(status="completed"), [self.completed.pk])
        self.assertEqual(self._ids(status="booked"), [self.booked.pk])

    def test_status_composes_with_client_and_salon_wide(self):
        rows = export_history(
            self.salon, self.other, now=NOW, status="cancelled")
        self.assertEqual([r["id"] for r in rows], [self.other_cancelled.pk])
        rows = export_history(self.salon, now=NOW, status="cancelled")
        self.assertEqual(
            [r["id"] for r in rows],
            [self.other_cancelled.pk, self.cancelled.pk])

    def test_status_composes_with_window(self):
        day = datetime.date(2026, 11, 1)
        self.assertEqual(
            self._ids(status="cancelled", start_date=day, end_date=day), [])
        self.assertEqual(
            self._ids(status="cancelled",
                      start_date=datetime.date(2026, 10, 31),
                      end_date=datetime.date(2026, 10, 31)),
            [self.cancelled.pk])

    def test_status_applies_before_limit(self):
        self.assertEqual(
            self._ids(status="completed", limit=1), [self.completed.pk])

    def test_unknown_status_is_empty(self):
        self.assertEqual(self._ids(status="no_such_status"), [])
        self.assertEqual(
            export_history_csv(
                self.salon, self.client, now=NOW, status="no_such_status"),
            ",".join(EXPORT_FIELDNAMES) + "\n")

    def test_csv_twin_matches_status_rows(self):
        text = export_history_csv(
            self.salon, self.client, now=NOW, status="cancelled")
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual([int(r["id"]) for r in parsed], [self.cancelled.pk])
        self.assertEqual(
            text, export_history_csv(
                self.salon, self.client, now=NOW, status="cancelled"))


class ExportHistoryStaffTests(TestCase):
    """The optional staff_member filter on the row's staff member."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Alice")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Bob")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        self.other = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=60)
        self.alice_new = self._appt(at(-1, 9))
        self.bob = self._appt(at(-2, 9), staff_member=self.staff2)
        self.alice_old = self._appt(
            at(-3, 9), status="cancelled")
        self.other_bob = self._appt(
            at(-1, 10), client=self.other, staff_member=self.staff2)

    def _appt(self, start, client=None, staff_member=None, status="booked"):
        return Appointment.objects.create(
            client=client or self.client,
            staff_member=staff_member or self.staff,
            service=self.service, start=start,
            end=start + datetime.timedelta(hours=1),
            status=status, origin="online")

    def _ids(self, **kw):
        return [r["id"] for r in export_history(
            self.salon, self.client, now=NOW, **kw)]

    def test_no_staff_is_previous_output(self):
        self.assertEqual(
            self._ids(),
            [self.alice_new.pk, self.bob.pk, self.alice_old.pk])
        self.assertEqual(
            export_history_csv(self.salon, self.client, now=NOW),
            export_history_csv(
                self.salon, self.client, now=NOW, staff_member=None))

    def test_staff_filters_exactly(self):
        self.assertEqual(
            self._ids(staff_member=self.staff),
            [self.alice_new.pk, self.alice_old.pk])
        self.assertEqual(
            self._ids(staff_member=self.staff2), [self.bob.pk])

    def test_staff_accepts_pk(self):
        self.assertEqual(
            self._ids(staff_member=self.staff2.pk), [self.bob.pk])

    def test_staff_composes_with_client_and_salon_wide(self):
        rows = export_history(
            self.salon, self.other, now=NOW, staff_member=self.staff2)
        self.assertEqual([r["id"] for r in rows], [self.other_bob.pk])
        rows = export_history(self.salon, now=NOW, staff_member=self.staff2)
        self.assertEqual(
            [r["id"] for r in rows], [self.other_bob.pk, self.bob.pk])

    def test_staff_composes_with_status_and_window(self):
        self.assertEqual(
            self._ids(staff_member=self.staff, status="cancelled"),
            [self.alice_old.pk])
        day = datetime.date(2026, 11, 1)
        self.assertEqual(
            self._ids(staff_member=self.staff2,
                      start_date=day, end_date=day), [])
        self.assertEqual(
            self._ids(staff_member=self.staff2,
                      start_date=datetime.date(2026, 10, 31),
                      end_date=datetime.date(2026, 10, 31)),
            [self.bob.pk])

    def test_staff_applies_before_limit(self):
        self.assertEqual(
            self._ids(staff_member=self.staff2, limit=1), [self.bob.pk])

    def test_staff_with_no_bookings_is_empty(self):
        idle = StaffMember.objects.create(
            salon=self.salon, display_name="Idle")
        self.assertEqual(self._ids(staff_member=idle), [])
        self.assertEqual(
            export_history_csv(
                self.salon, self.client, now=NOW, staff_member=idle),
            ",".join(EXPORT_FIELDNAMES) + "\n")

    def test_csv_twin_matches_staff_rows(self):
        text = export_history_csv(
            self.salon, self.client, now=NOW, staff_member=self.staff2)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual([int(r["id"]) for r in parsed], [self.bob.pk])
