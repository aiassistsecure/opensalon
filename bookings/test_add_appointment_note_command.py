"""Tests for the add_appointment_note management command.

The command is a thin wrapper around ``bookings.notes.add_note``:
these tests pin that a real run creates exactly one note attached
to the right appointment, that ``--dry-run`` creates none but
prints the would-be note (with the service's validation still
applied), and that unknown salon/appointment, salon mismatch, and
empty text surface as ``CommandError`` with nothing written.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment, AppointmentNote
from clients.models import Client, ClientNote
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


class AddAppointmentNoteCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.appointment = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service,
            start=datetime.datetime.combine(
                DAY, datetime.time(9, 0), tzinfo=UTC),
            end=datetime.datetime.combine(
                DAY, datetime.time(9, 45), tzinfo=UTC))
        self.other_appointment = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service,
            start=datetime.datetime.combine(
                DAY, datetime.time(13, 0), tzinfo=UTC),
            end=datetime.datetime.combine(
                DAY, datetime.time(13, 45), tzinfo=UTC))

    def test_real_run_creates_exactly_one_note_on_right_appointment(self):
        out = io.StringIO()
        call_command(
            "add_appointment_note", appointment_id=self.appointment.pk,
            text="Prefers quiet room", author="Front Desk", stdout=out)
        self.assertEqual(AppointmentNote.objects.count(), 1)
        (note,) = AppointmentNote.objects.all()
        self.assertEqual(note.appointment, self.appointment)
        self.assertEqual(note.body, "Prefers quiet room")
        self.assertEqual(note.author_name, "Front Desk")
        self.assertEqual(self.other_appointment.notes.count(), 0)
        self.assertIn("appointment", out.getvalue())
        self.assertIn("Prefers quiet room", out.getvalue())

    def test_real_run_string_args_and_salon_scoping(self):
        out = io.StringIO()
        call_command(
            "add_appointment_note", "--appointment-id",
            str(self.appointment.pk), "--salon-id", str(self.salon.pk),
            "--text", "Arrive early", stdout=out)
        self.assertEqual(AppointmentNote.objects.count(), 1)
        (note,) = AppointmentNote.objects.all()
        self.assertEqual(note.author_name, "")

    def test_real_run_creates_no_client_record_note(self):
        call_command(
            "add_appointment_note", appointment_id=self.appointment.pk,
            text="This visit only", stdout=io.StringIO())
        self.assertEqual(ClientNote.objects.count(), 0)

    def test_dry_run_creates_none_but_prints_would_be_note(self):
        out = io.StringIO()
        call_command(
            "add_appointment_note", appointment_id=self.appointment.pk,
            salon_id=self.salon.pk, text="Would-be note",
            author="Desk", dry_run=True, stdout=out)
        self.assertEqual(AppointmentNote.objects.count(), 0)
        text = out.getvalue()
        self.assertIn("Dry run", text)
        self.assertIn("Would-be note", text)
        self.assertIn("Desk", text)
        self.assertIn(str(self.appointment.pk), text)

    def test_dry_run_flag_form(self):
        out = io.StringIO()
        call_command(
            "add_appointment_note", "--appointment-id",
            str(self.appointment.pk), "--text", "Preview",
            "--dry-run", stdout=out)
        self.assertEqual(AppointmentNote.objects.count(), 0)
        self.assertIn("Preview", out.getvalue())

    def test_dry_run_empty_text_is_command_error_and_writes_nothing(self):
        with self.assertRaises(CommandError):
            call_command(
                "add_appointment_note",
                appointment_id=self.appointment.pk, text="   ",
                dry_run=True, stdout=io.StringIO())
        self.assertEqual(AppointmentNote.objects.count(), 0)

    def test_empty_text_is_command_error_and_writes_nothing(self):
        for text in ("", "   "):
            with self.assertRaises(CommandError):
                call_command(
                    "add_appointment_note",
                    appointment_id=self.appointment.pk, text=text,
                    stdout=io.StringIO())
        self.assertEqual(AppointmentNote.objects.count(), 0)

    def test_unknown_appointment_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "add_appointment_note", appointment_id=999999,
                text="Hello", stdout=io.StringIO())
        self.assertEqual(AppointmentNote.objects.count(), 0)

    def test_unknown_salon_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "add_appointment_note",
                appointment_id=self.appointment.pk, salon_id=999999,
                text="Hello", stdout=io.StringIO())
        self.assertEqual(AppointmentNote.objects.count(), 0)

    def test_appointment_outside_salon_is_command_error(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        with self.assertRaises(CommandError):
            call_command(
                "add_appointment_note",
                appointment_id=self.appointment.pk, salon_id=other.pk,
                text="Hello", stdout=io.StringIO())
        self.assertEqual(AppointmentNote.objects.count(), 0)

    def test_dry_run_unknown_appointment_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "add_appointment_note", appointment_id=999999,
                text="Hello", dry_run=True, stdout=io.StringIO())
        self.assertEqual(AppointmentNote.objects.count(), 0)
