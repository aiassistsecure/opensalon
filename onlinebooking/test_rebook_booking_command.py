"""Tests for the rebook_booking management command.

Thin wrapper over ``onlinebooking.rebook.rebook_appointment``:
real runs create a NEW appointment (source unchanged),
``--dry-run`` previews without writing (read-only validate
helper, NEDB-safe) and prints the would-be booking, and
invalid rebooks (cancelled source, unrostered slot, toggle
off, unknown or out-of-salon appointment) surface as
``CommandError`` with nothing created. Tiny synthetic fixtures.
"""
import datetime
import io

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

PAST_MONDAY = datetime.date(2026, 10, 26)
MONDAY = datetime.date(2026, 11, 2)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class RebookBookingCommandTests(TestCase):
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
        self.source = Appointment.objects.create(
            client=self.client, staff_member=self.staff, service=self.service,
            start=at(PAST_MONDAY, 10), end=at(PAST_MONDAY, 10, 45),
            status=Appointment.Status.COMPLETED)

    def test_real_run_creates_new_and_keeps_source(self):
        out = io.StringIO()
        call_command("rebook_booking", appointment_id=self.source.pk,
                     new_start=at(MONDAY, 11), stdout=out)
        self.assertEqual(Appointment.objects.count(), 2)
        new = Appointment.objects.exclude(pk=self.source.pk).get()
        self.assertEqual((new.start, new.end), (at(MONDAY, 11), at(MONDAY, 11, 45)))
        self.assertEqual(new.status, Appointment.Status.BOOKED)
        self.assertEqual(new.client, self.client)
        self.source.refresh_from_db()
        self.assertEqual(self.source.start, at(PAST_MONDAY, 10))
        text = out.getvalue()
        self.assertIn("Rebooked appointment", text)
        self.assertIn(str(new.pk), text)

    def test_real_run_string_args_explicit_end_and_salon(self):
        call_command("rebook_booking", "--appointment-id", str(self.source.pk),
                     "--salon-id", str(self.salon.pk),
                     "--new-start", "2026-11-02T14:00:00+00:00",
                     "--new-end", "2026-11-02T15:00:00+00:00",
                     stdout=io.StringIO())
        new = Appointment.objects.exclude(pk=self.source.pk).get()
        self.assertEqual((new.start, new.end), (at(MONDAY, 14), at(MONDAY, 15)))

    def test_dry_run_prints_booking_and_writes_nothing(self):
        out = io.StringIO()
        call_command("rebook_booking", appointment_id=self.source.pk,
                     new_start=at(MONDAY, 13), dry_run=True, stdout=out)
        self.assertEqual(Appointment.objects.count(), 1)
        text = out.getvalue()
        self.assertIn("Dry run", text)
        self.assertIn(at(MONDAY, 13).isoformat(), text)
        self.assertIn("no appointment created", text)

    def test_dry_run_no_write_regression_count_status_times(self):
        call_command("rebook_booking", appointment_id=self.source.pk,
                     new_start=at(MONDAY, 13), dry_run=True,
                     stdout=io.StringIO())
        self.source.refresh_from_db()
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(self.source.status, Appointment.Status.COMPLETED)
        self.assertEqual((self.source.start, self.source.end),
                         (at(PAST_MONDAY, 10), at(PAST_MONDAY, 10, 45)))

    def test_dry_run_flag_form_writes_nothing(self):
        out = io.StringIO()
        call_command("rebook_booking", "--appointment-id", str(self.source.pk),
                     "--new-start", "2026-11-02T13:00:00+00:00",
                     "--dry-run", stdout=out)
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertIn("Dry run", out.getvalue())

    def test_cancelled_source_is_command_error_creates_nothing(self):
        Appointment.objects.filter(pk=self.source.pk).update(
            status=Appointment.Status.CANCELLED)
        for kw in ({}, {"dry_run": True}):
            with self.assertRaises(CommandError):
                call_command("rebook_booking", appointment_id=self.source.pk,
                             new_start=at(MONDAY, 11), stdout=io.StringIO(), **kw)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_invalid_slot_and_toggle_off_are_command_errors(self):
        with self.assertRaises(CommandError):
            call_command("rebook_booking", appointment_id=self.source.pk,
                         new_start=at(MONDAY, 18), stdout=io.StringIO())
        self.staff.online_bookable = False
        self.staff.save(update_fields=["online_bookable"])
        with self.assertRaises(CommandError):
            call_command("rebook_booking", appointment_id=self.source.pk,
                         new_start=at(MONDAY, 11), stdout=io.StringIO())
        self.assertEqual(Appointment.objects.count(), 1)

    def test_unknown_and_out_of_salon_are_command_errors(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        for kwargs in (dict(appointment_id=999999),
                       dict(appointment_id=self.source.pk, salon_id=999999),
                       dict(appointment_id=self.source.pk, salon_id=other.pk)):
            with self.assertRaises(CommandError):
                call_command("rebook_booking", new_start=at(MONDAY, 11),
                             stdout=io.StringIO(), **kwargs)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_unparseable_new_start_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command("rebook_booking", appointment_id=self.source.pk,
                         new_start="not-a-time", stdout=io.StringIO())
        self.assertEqual(Appointment.objects.count(), 1)
