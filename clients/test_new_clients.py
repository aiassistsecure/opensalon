"""Tests for new clients per period (core, CSV export, command).

Synthetic fixtures only. Definition under test: a client is new in
[start_date, end_date] when their earliest non-cancelled
appointment starts inside that inclusive whole-day window — which
means no earlier non-cancelled appointment exists. Client.created_at
must play no part.
"""
import csv
import datetime
import io

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from clients.new_clients import NewClient, new_client_count, new_clients
from clients.new_clients_export import (
    NEW_CLIENTS_FIELDNAMES,
    export_new_clients,
    export_new_clients_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
START = datetime.date(2026, 10, 1)
END = datetime.date(2026, 10, 31)


def at(day, hour=12):
    return datetime.datetime(2026, 10, day, hour, tzinfo=UTC)


class NewClientsBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self._n = 0

    def _client(self, salon=None):
        self._n += 1
        return Client.objects.create(
            salon=salon or self.salon, first_name="Client",
            last_name=f"{self._n:03d}")

    def _appt(self, client, start, **kw):
        return Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            start=start, end=start + datetime.timedelta(minutes=45), **kw)

    def _ids(self, rows):
        return [r.client_id for r in rows]


class CoreTests(NewClientsBase):
    def test_first_visit_in_window_included(self):
        c = self._client()
        appt = self._appt(c, at(10))
        self._appt(c, at(20))
        rows = new_clients(self.salon, START, END)
        self.assertEqual(self._ids(rows), [c.pk])
        self.assertIsInstance(rows[0], NewClient)
        self.assertEqual(rows[0].first_appointment, appt.start)
        self.assertEqual(rows[0].first_visit, appt.start)
        self.assertEqual(rows[0].first_appointment_date, START.replace(day=10))
        self.assertEqual(new_client_count(self.salon, START, END), 1)

    def test_window_boundaries_are_inclusive_whole_days(self):
        first = self._client(); self._appt(first, at(1, hour=0))
        last = self._client(); self._appt(last, at(31, hour=23))
        after = self._client()
        self._appt(after, datetime.datetime(2026, 11, 1, 0, tzinfo=UTC))
        before = self._client()
        self._appt(before, datetime.datetime(2026, 9, 30, 23, tzinfo=UTC))
        rows = new_clients(self.salon, START, END)
        self.assertEqual(self._ids(rows), [first.pk, last.pk])

    def test_earlier_non_cancelled_excludes(self):
        c = self._client()
        self._appt(c, datetime.datetime(2026, 5, 1, 12, tzinfo=UTC))
        self._appt(c, at(10))
        self.assertEqual(new_clients(self.salon, START, END), [])

    def test_earlier_cancelled_does_not_exclude(self):
        c = self._client()
        self._appt(c, datetime.datetime(2026, 5, 1, 12, tzinfo=UTC),
                   status=Appointment.Status.CANCELLED)
        self._appt(c, at(10))
        self.assertEqual(self._ids(new_clients(self.salon, START, END)), [c.pk])

    def test_cancelled_in_window_is_not_first_visit(self):
        c = self._client()
        self._appt(c, at(3), status=Appointment.Status.CANCELLED)
        real = self._appt(c, at(12))
        rows = new_clients(self.salon, START, END)
        self.assertEqual(rows[0].first_appointment, real.start)

    def test_cancelled_only_and_never_booked_excluded(self):
        c = self._client()
        self._appt(c, at(10), status=Appointment.Status.CANCELLED)
        self._client()
        self.assertEqual(new_clients(self.salon, START, END), [])

    def test_created_at_is_ignored(self):
        old_created = self._client()
        Client.objects.filter(pk=old_created.pk).update(
            created_at=datetime.datetime(2020, 1, 1, tzinfo=UTC))
        self._appt(old_created, datetime.datetime(2026, 5, 1, tzinfo=UTC))
        recent_created = self._client()  # created now, first visit in window
        self._appt(recent_created, at(5))
        rows = new_clients(self.salon, START, END)
        self.assertEqual(self._ids(rows), [recent_created.pk])

    def test_salon_scope_and_no_salon(self):
        mine = self._client(); self._appt(mine, at(10))
        theirs = self._client(salon=self.other); self._appt(theirs, at(11))
        self.assertEqual(self._ids(new_clients(self.salon, START, END)), [mine.pk])
        self.assertEqual(
            set(self._ids(new_clients(start_date=START, end_date=END))),
            {mine.pk, theirs.pk})

    def test_ordering_first_visit_then_id(self):
        later = self._client(); self._appt(later, at(20))
        earlier = self._client(); self._appt(earlier, at(5))
        tie = self._client(); self._appt(tie, at(5))
        rows = new_clients(self.salon, START, END)
        self.assertEqual(self._ids(rows), [earlier.pk, tie.pk, later.pk])

    def test_aliases_and_iso_strings(self):
        c = self._client(); self._appt(c, at(10))
        rows = new_clients(self.salon, period_start="2026-10-01",
                           period_end="2026-10-31")
        self.assertEqual(self._ids(rows), [c.pk])

    def test_missing_or_reversed_window_raises(self):
        with self.assertRaises(ValueError):
            new_clients(self.salon, START)
        with self.assertRaises(ValueError):
            new_clients(self.salon, END, START)


class ExportTests(NewClientsBase):
    def test_dict_and_csv_agree(self):
        c = self._client(); appt = self._appt(c, at(10))
        records = export_new_clients(self.salon, START, END)
        self.assertEqual(records, [{
            "client_id": c.pk, "first_name": "Client", "last_name": "001",
            "first_appointment": appt.start.isoformat(),
            "first_appointment_date": "2026-10-10"}])
        parsed = list(csv.DictReader(io.StringIO(
            export_new_clients_csv(self.salon, START, END))))
        self.assertEqual(parsed[0]["client_id"], str(c.pk))
        self.assertEqual(parsed[0]["first_appointment_date"], "2026-10-10")

    def test_header_only_when_none(self):
        self.assertEqual(export_new_clients(self.salon, START, END), [])
        self.assertEqual(export_new_clients_csv(self.salon, START, END),
                         ",".join(NEW_CLIENTS_FIELDNAMES) + "\n")


class CommandTests(NewClientsBase):
    def test_stdout_matches_service(self):
        c = self._client(); self._appt(c, at(10))
        out = io.StringIO()
        call_command("export_new_clients", salon_id=self.salon.id,
                     start_date="2026-10-01", end_date="2026-10-31", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_new_clients_csv(self.salon, START, END))

    def test_unknown_salon_and_missing_dates_and_reversed(self):
        with self.assertRaises(CommandError):
            call_command("export_new_clients", salon_id=999999,
                         start_date="2026-10-01", end_date="2026-10-31",
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_new_clients", salon_id=self.salon.id,
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_new_clients", salon_id=self.salon.id,
                         start_date="2026-10-31", end_date="2026-10-01",
                         stdout=io.StringIO())
