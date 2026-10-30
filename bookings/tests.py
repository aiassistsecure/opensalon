from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment, AppointmentNote
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember


class AppointmentModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts"
        )
        self.service = Service.objects.create(
            category=self.category, name="Haircut", service_minutes=45
        )
        self.start = timezone.now() + timedelta(days=1)
        self.end = self.start + timedelta(minutes=45)

    def _create(self, **kwargs):
        defaults = dict(
            client=self.client, staff_member=self.staff,
            service=self.service, start=self.start, end=self.end,
        )
        defaults.update(kwargs)
        return Appointment.objects.create(**defaults)

    def test_creation_and_fks(self):
        appt = self._create()
        self.assertEqual(appt.client, self.client)
        self.assertEqual(appt.staff_member, self.staff)
        self.assertEqual(appt.service, self.service)
        self.assertIn(appt, list(self.client.appointments.all()))
        self.assertIn(appt, list(self.staff.appointments.all()))
        self.assertIn(appt, list(self.service.appointments.all()))
        self.assertIsNotNone(appt.created_at)
        self.assertIsNotNone(appt.updated_at)

    def test_status_default_is_booked(self):
        appt = self._create()
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.BOOKED)
        self.assertEqual(appt.status, "booked")

    def test_status_choices(self):
        self.assertEqual(
            [c[0] for c in Appointment.Status.choices],
            ["booked", "confirmed", "arrived", "in_service",
             "completed", "cancelled", "no_show"],
        )
        appt = self._create(status=Appointment.Status.CONFIRMED)
        self.assertEqual(appt.status, "confirmed")

    def test_ordering_by_start(self):
        later = self._create(start=self.start + timedelta(hours=2),
                             end=self.end + timedelta(hours=2))
        earlier = self._create()
        self.assertEqual(list(Appointment.objects.all()), [earlier, later])
        self.assertEqual(Appointment._meta.ordering, ["start"])

    def test_str(self):
        appt = self._create()
        self.assertIn("Haircut", str(appt))
        self.assertIn("Test Example", str(appt))


class AppointmentNoteModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts"
        )
        self.service = Service.objects.create(
            category=self.category, name="Haircut", service_minutes=45
        )
        start = timezone.now() + timedelta(days=1)
        self.appointment = Appointment.objects.create(
            client=self.client, staff_member=self.staff, service=self.service,
            start=start, end=start + timedelta(minutes=45),
        )

    def test_note_attachment(self):
        note = AppointmentNote.objects.create(
            appointment=self.appointment, body="Running 10 min late.",
            author_name="Front Desk",
        )
        self.assertEqual(note.appointment, self.appointment)
        self.assertIn(note, list(self.appointment.notes.all()))
        self.assertEqual(note.author_name, "Front Desk")
        self.assertIsNotNone(note.created_at)

    def test_note_cascade_on_appointment_delete(self):
        AppointmentNote.objects.create(appointment=self.appointment, body="One")
        self.appointment.delete()
        self.assertEqual(AppointmentNote.objects.count(), 0)

    def test_blank_author_allowed(self):
        note = AppointmentNote.objects.create(
            appointment=self.appointment, body="No author"
        )
        self.assertEqual(note.author_name, "")
