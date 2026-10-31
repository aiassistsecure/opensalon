import csv
import io
from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.due import due_reminders
from messaging.due_export import (
    DUE_EXPORT_FIELDNAMES,
    due_export_csv,
    export_due_reminders,
    export_due_reminders_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="salon@example.com",
)
class DueExportBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other Stylist")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.window_start = timezone.now() + timedelta(hours=1)
        self.window_end = self.window_start + timedelta(hours=24)
        self.start = self.window_start + timedelta(hours=2)

    def _appointment(self, salon=None, staff=None, start=None, **client_kwargs):
        salon = salon or self.salon
        defaults = dict(
            salon=salon, first_name="Test", last_name="Example",
            phone="555-0100", email="client@example.com",
            email_opt_in=True, sms_opt_in=True)
        defaults.update(client_kwargs)
        client = Client.objects.create(**defaults)
        start = start or self.start
        return Appointment.objects.create(
            client=client, staff_member=staff or self.staff,
            service=self.service, start=start,
            end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)


class HeaderAndDueRowTests(DueExportBase):
    def test_header_and_due_rows_one_per_eligible_channel(self):
        appt = self._appointment()
        text = export_due_reminders_csv(
            self.salon, self.window_start, self.window_end)
        self.assertEqual(
            text.splitlines()[0], ",".join(DUE_EXPORT_FIELDNAMES))
        rows = _rows(text)
        self.assertEqual([r["channel"] for r in rows], ["email", "sms"])
        for row in rows:
            self.assertEqual(list(row), DUE_EXPORT_FIELDNAMES)
            self.assertEqual(int(row["salon_id"]), self.salon.pk)
            self.assertEqual(int(row["appointment_id"]), appt.pk)
            self.assertEqual(int(row["client_id"]), appt.client_id)
            self.assertEqual(row["client_name"], "Test Example")
            self.assertEqual(row["due_at"], appt.start.isoformat())

    def test_list_agrees_with_csv_alias_and_listing(self):
        appt = self._appointment()
        rows = export_due_reminders(
            self.salon, self.window_start, self.window_end)
        listing = due_reminders(self.window_start, self.window_end)
        expected_channels = [
            c for entry in listing for c in entry.eligible_channels]
        self.assertEqual([r["channel"] for r in rows], expected_channels)
        self.assertTrue(all(r["appointment_id"] == appt.pk for r in rows))
        parsed = [
            {**r, "salon_id": int(r["salon_id"]),
             "appointment_id": int(r["appointment_id"]),
             "client_id": int(r["client_id"])}
            for r in _rows(export_due_reminders_csv(
                self.salon, self.window_start, self.window_end))]
        self.assertEqual(parsed, rows)
        self.assertEqual(
            due_export_csv(self.salon, self.window_start, self.window_end),
            export_due_reminders_csv(
                self.salon, self.window_start, self.window_end))


class OptInTests(DueExportBase):
    def test_email_opt_out_excluded_from_email_rows(self):
        self._appointment(email_opt_in=False, sms_opt_in=True)
        rows = export_due_reminders(
            self.salon, self.window_start, self.window_end)
        self.assertEqual([r["channel"] for r in rows], ["sms"])

    def test_sms_opt_out_excluded_from_sms_rows(self):
        self._appointment(email_opt_in=True, sms_opt_in=False)
        rows = export_due_reminders(
            self.salon, self.window_start, self.window_end)
        self.assertEqual([r["channel"] for r in rows], ["email"])

    def test_opted_out_of_both_produces_no_rows(self):
        self._appointment(email_opt_in=False, sms_opt_in=False)
        self.assertEqual(
            export_due_reminders(
                self.salon, self.window_start, self.window_end), [])


class WindowAndScopeTests(DueExportBase):
    def test_not_yet_due_excluded(self):
        self._appointment(start=self.window_end + timedelta(hours=1))
        self._appointment(start=self.window_start - timedelta(hours=1))
        due = self._appointment()
        rows = export_due_reminders(
            self.salon, self.window_start, self.window_end)
        self.assertEqual(
            {r["appointment_id"] for r in rows}, {due.pk})
        self.assertEqual(len(rows), 2)

    def test_salon_scoping_excludes_other_salon(self):
        own = self._appointment()
        self._appointment(salon=self.other, staff=self.other_staff)
        rows = export_due_reminders(
            self.salon, self.window_start, self.window_end)
        self.assertEqual(
            {r["appointment_id"] for r in rows}, {own.pk})
        self.assertTrue(all(r["salon_id"] == self.salon.pk for r in rows))
        other_rows = export_due_reminders(
            self.other, self.window_start, self.window_end)
        self.assertEqual(
            {r["salon_id"] for r in other_rows}, {self.other.pk})

    def test_empty_window_is_header_only(self):
        header = ",".join(DUE_EXPORT_FIELDNAMES) + "\n"
        self.assertEqual(
            export_due_reminders(
                self.salon, self.window_start, self.window_end), [])
        self.assertEqual(
            export_due_reminders_csv(
                self.salon, self.window_start, self.window_end), header)
        self.assertEqual(
            export_due_reminders_csv(
                None, self.window_start, self.window_end), header)


class ReadOnlyTests(DueExportBase):
    def test_export_sends_and_mutates_nothing(self):
        self._appointment()
        before = Appointment.objects.count()
        export_due_reminders_csv(
            self.salon, self.window_start, self.window_end)
        self.assertEqual(Appointment.objects.count(), before)
        self.assertEqual(len(mail.outbox), 0)
