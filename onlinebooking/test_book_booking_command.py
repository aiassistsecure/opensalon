"""Tests for the book_booking management command.

Thin wrapper over ``onlinebooking.services.create_online_booking``:
real runs create a validated online booking (toggle, roster,
overlap, cross-salon, and active rules enforced; origin marked
online), ``--dry-run`` previews via the read-only validate twin
without writing (NEDB-safe), and invalid input surfaces as
``CommandError`` with nothing created. Tiny synthetic fixtures.
"""
import datetime
import io
import json

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment, AppointmentNote
from clients.models import Client, ClientNote
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class BookBookingCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Online Stylist", online_bookable=True)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0))

    def _book(self, out=None, **kw):
        kw.setdefault("client_id", self.client.pk)
        kw.setdefault("staff_member_id", self.staff.pk)
        kw.setdefault("service_id", self.service.pk)
        kw.setdefault("start", at(MONDAY, 10))
        return call_command("book_booking", stdout=out or io.StringIO(), **kw)

    def test_real_run_creates_with_default_end_booked_status_and_online_origin(self):
        out = io.StringIO()
        self._book(out=out)
        appt = Appointment.objects.get()
        self.assertEqual((appt.start, appt.end), (at(MONDAY, 10), at(MONDAY, 10, 45)))
        self.assertEqual(appt.status, Appointment.Status.BOOKED)
        self.assertEqual(appt.origin, Appointment.Origin.ONLINE)
        self.assertEqual((appt.client, appt.staff_member, appt.service),
                         (self.client, self.staff, self.service))
        self.assertIn("Booked appointment", out.getvalue())
        self.assertIn(str(appt.pk), out.getvalue())

    def test_string_args_explicit_end_salon_and_note(self):
        out = io.StringIO()
        call_command(
            "book_booking", "--client-id", str(self.client.pk),
            "--staff-member-id", str(self.staff.pk),
            "--service-id", str(self.service.pk),
            "--salon-id", str(self.salon.pk),
            "--start", "2026-11-02T13:00:00+00:00",
            "--end", "2026-11-02T14:00:00+00:00",
            "--note", "Online booking", "--note-author", "Client",
            stdout=out)
        appt = Appointment.objects.get()
        self.assertEqual((appt.start, appt.end), (at(MONDAY, 13), at(MONDAY, 14)))
        self.assertEqual(appt.origin, Appointment.Origin.ONLINE)
        note = AppointmentNote.objects.get()
        self.assertEqual((note.appointment, note.body, note.author_name),
                         (appt, "Online booking", "Client"))
        self.assertEqual(ClientNote.objects.count(), 0)

    def test_toggle_off_is_command_error_real_and_dry_run(self):
        self.staff.online_bookable = False
        self.staff.save(update_fields=["online_bookable"])
        for kw in ({}, {"dry_run": True}):
            with self.assertRaises(CommandError):
                self._book(**kw)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_outside_roster_and_overlap_are_command_errors(self):
        self._book()
        for start in (at(MONDAY, 18), at(MONDAY, 10, 30)):
            with self.assertRaises(CommandError):
                self._book(start=start)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_cross_salon_and_inactive_are_command_errors(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        outsider = Client.objects.create(
            salon=other, first_name="Out", last_name="Sider")
        with self.assertRaises(CommandError):
            self._book(client_id=outsider.pk)
        self.staff.active = False
        self.staff.save(update_fields=["active"])
        with self.assertRaises(CommandError):
            self._book()
        self.assertEqual(Appointment.objects.count(), 0)

    def test_unknown_ids_and_out_of_salon_are_command_errors(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        for kw in (dict(client_id=999999), dict(staff_member_id=999999),
                   dict(service_id=999999), dict(salon_id=999999),
                   dict(salon_id=other.pk)):
            with self.assertRaises(CommandError):
                self._book(**kw)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_unparseable_naive_and_end_before_start_are_command_errors(self):
        naive = datetime.datetime.combine(MONDAY, datetime.time(10, 0))
        for kw in (dict(start="not-a-time"), dict(start=naive),
                   dict(end=at(MONDAY, 9, 30))):
            with self.assertRaises(CommandError):
                self._book(**kw)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_dry_run_prints_booking_and_writes_nothing(self):
        out = io.StringIO()
        self._book(out=out, dry_run=True, note="Online booking")
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AppointmentNote.objects.count(), 0)
        text = out.getvalue()
        self.assertIn("Dry run", text)
        self.assertIn(at(MONDAY, 10).isoformat(), text)
        self.assertIn(at(MONDAY, 10, 45).isoformat(), text)
        self.assertIn("no appointment created", text)

    def test_dry_run_flag_form(self):
        out = io.StringIO()
        call_command(
            "book_booking", "--client-id", str(self.client.pk),
            "--staff-member-id", str(self.staff.pk),
            "--service-id", str(self.service.pk),
            "--start", "2026-11-02T10:00:00+00:00", "--dry-run", stdout=out)
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertIn("Dry run", out.getvalue())

    def test_dry_run_then_real_run_still_books(self):
        self._book(dry_run=True)
        self.assertEqual(Appointment.objects.count(), 0)
        self._book()
        self.assertEqual(Appointment.objects.count(), 1)

    def test_explicit_text_format_matches_default(self):
        out = io.StringIO()
        self._book(out=out, format="text")
        appt = Appointment.objects.get()
        self.assertEqual(
            out.getvalue(),
            f"Booked appointment {appt.pk}: client {self.client.pk} "
            f"with staff {self.staff.pk}, service {self.service.pk}: "
            f"{at(MONDAY, 10).isoformat()} -> "
            f"{at(MONDAY, 10, 45).isoformat()}, status booked.\n")

    def test_json_output_parses_and_carries_facts(self):
        out = io.StringIO()
        self._book(out=out, format="json")
        appt = Appointment.objects.get()
        text = out.getvalue()
        self.assertNotIn("Booked appointment", text)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertEqual(json.loads(text), {
            "id": appt.pk, "client_id": self.client.pk,
            "staff_member_id": self.staff.pk,
            "service_id": self.service.pk,
            "start": at(MONDAY, 10).isoformat(),
            "end": at(MONDAY, 10, 45).isoformat(),
            "status": "booked", "dry_run": False})

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(
            "book_booking", "--client-id", str(self.client.pk),
            "--staff-member-id", str(self.staff.pk),
            "--service-id", str(self.service.pk),
            "--start", "2026-11-02T10:00:00+00:00",
            "--format", "json", stdout=out)
        row = json.loads(out.getvalue())
        appt = Appointment.objects.get()
        self.assertEqual(
            (row["id"], row["client_id"], row["status"], row["dry_run"]),
            (appt.pk, self.client.pk, "booked", False))

    def test_dry_run_json_reports_dry_run_and_writes_nothing(self):
        out = io.StringIO()
        self._book(out=out, dry_run=True, format="json",
                   note="Online booking")
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AppointmentNote.objects.count(), 0)
        text = out.getvalue()
        self.assertNotIn("Dry run", text)
        self.assertEqual(json.loads(text), {
            "id": None, "client_id": self.client.pk,
            "staff_member_id": self.staff.pk,
            "service_id": self.service.pk,
            "start": at(MONDAY, 10).isoformat(),
            "end": at(MONDAY, 10, 45).isoformat(),
            "status": "booked", "note": "Online booking",
            "dry_run": True})

    def test_json_errors_still_command_error(self):
        for kw in (dict(client_id=999999), dict(start=at(MONDAY, 18)),
                   dict(start="not-a-time")):
            with self.assertRaises(CommandError):
                self._book(format="json", **kw)
        with self.assertRaises(CommandError):
            self._book(format="bogus")
        with self.assertRaises(CommandError):
            self._book(dry_run=True, format="json", start=at(MONDAY, 18))
        self.assertEqual(Appointment.objects.count(), 0)

    def test_dry_run_invalid_same_error_and_writes_nothing(self):
        with self.assertRaises(CommandError) as real:
            self._book(start=at(MONDAY, 18))
        with self.assertRaises(CommandError) as preview:
            self._book(start=at(MONDAY, 18), dry_run=True)
        self.assertEqual(str(preview.exception), str(real.exception))
        self.assertEqual(Appointment.objects.count(), 0)
