import csv
import io
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.models import ReminderSend
from messaging.send_export import RECORD_FIELDNAMES, send_export_row
from messaging.send_search import search_sends
from messaging.send_search_export import (
    EXPORT_FIELDNAMES,
    export_search_sends,
    export_search_sends_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
DAY1 = date(2026, 3, 2)
DAY2 = date(2026, 3, 3)


def _at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=UTC)


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


class SendSearchExportBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other Stylist")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)

    def _send(self, first, last, channel, when, salon=None, staff=None,
              detail=""):
        salon = salon or self.salon
        staff = staff or self.staff
        client = Client.objects.create(
            salon=salon, first_name=first, last_name=last,
            email="c@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True)
        start = timezone.now() + timedelta(days=1)
        appt = Appointment.objects.create(
            client=client, staff_member=staff, service=self.service,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)
        return ReminderSend.objects.create(
            appointment=appt, client=client, channel=channel,
            status="sent", sent_at=when, detail=detail)


class MatchTests(SendSearchExportBase):
    def test_match_by_first_and_last_name_case_insensitive(self):
        hit = self._send("Alice", "Smith", "email", _at(DAY1, 9),
                         detail="ref-1")
        self._send("Bob", "Jones", "email", _at(DAY1, 10))
        for term in ("ali", "SMITH"):
            rows = export_search_sends(self.salon, term)
            self.assertEqual([r["id"] for r in rows], [hit.pk])
        self.assertEqual(list(rows[0]), EXPORT_FIELDNAMES)
        self.assertEqual(EXPORT_FIELDNAMES, RECORD_FIELDNAMES)
        self.assertEqual(rows[0], send_export_row(hit))
        self.assertEqual(rows[0]["salon_id"], self.salon.pk)
        self.assertEqual(rows[0]["detail"], "ref-1")
        self.assertEqual(rows[0]["sent_at"], hit.sent_at.isoformat())
        for forbidden in ("email", "phone", "first_name", "last_name"):
            self.assertNotIn(forbidden, rows[0])

    def test_rows_verbatim_from_search_service_newest_first(self):
        older = self._send("Alice", "Smith", "email", _at(DAY1, 9))
        newer = self._send("Alice", "Brown", "sms", _at(DAY2, 9))
        self._send("Bob", "Jones", "email", _at(DAY2, 10))
        rows = export_search_sends(self.salon, "alice")
        expected = [s.pk for s in search_sends(self.salon, "alice")]
        self.assertEqual([r["id"] for r in rows], expected)
        self.assertEqual([r["id"] for r in rows], [newer.pk, older.pk])

    def test_csv_agrees_with_list_export(self):
        self._send("Alice", "Smith", "email", _at(DAY1, 9))
        self._send("Alice", "Brown", "sms", _at(DAY2, 9))
        text = export_search_sends_csv(self.salon, "alice")
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        parsed = _rows(text)
        listed = export_search_sends(self.salon, "alice")
        self.assertEqual(len(parsed), len(listed))
        self.assertEqual(
            [int(r["id"]) for r in parsed], [r["id"] for r in listed])
        self.assertEqual(parsed[0]["channel"], listed[0]["channel"])


class NoMatchAndEmptyTermTests(SendSearchExportBase):
    def test_no_match_is_empty_and_header_only_csv(self):
        self._send("Alice", "Smith", "email", _at(DAY1, 9))
        self.assertEqual(export_search_sends(self.salon, "zzz"), [])
        self.assertEqual(
            export_search_sends_csv(self.salon, "zzz"),
            ",".join(EXPORT_FIELDNAMES) + "\n")

    def test_empty_term_exports_whole_salon_log(self):
        first = self._send("Alice", "Smith", "email", _at(DAY1, 9))
        second = self._send("Bob", "Jones", "sms", _at(DAY2, 9))
        for term in (None, "", "  "):
            rows = export_search_sends(self.salon, term)
            self.assertEqual(
                [r["id"] for r in rows], [second.pk, first.pk])
        self.assertEqual(
            len(_rows(export_search_sends_csv(self.salon))), 2)


class SalonScopingTests(SendSearchExportBase):
    def test_other_salon_never_exported(self):
        own = self._send("Alice", "Smith", "email", _at(DAY1, 9))
        self._send("Alice", "Smith", "email", _at(DAY1, 10),
                   salon=self.other, staff=self.other_staff)
        rows = export_search_sends(self.salon, "alice")
        self.assertEqual([r["id"] for r in rows], [own.pk])
        self.assertEqual(len(export_search_sends(self.other, "alice")), 1)

    def test_none_salon_is_empty_and_header_only(self):
        self._send("Alice", "Smith", "email", _at(DAY1, 9))
        self.assertEqual(export_search_sends(None, "alice"), [])
        self.assertEqual(
            export_search_sends_csv(None, "alice"),
            ",".join(EXPORT_FIELDNAMES) + "\n")


class PassthroughAndReadOnlyTests(SendSearchExportBase):
    def test_channel_and_date_filters_pass_through(self):
        hit = self._send("Alice", "Smith", "sms", _at(DAY2, 9))
        self._send("Alice", "Smith", "email", _at(DAY2, 9))
        self._send("Alice", "Smith", "sms", _at(DAY1, 9))
        rows = export_search_sends(
            self.salon, "smith", channel="sms", start=DAY2, end=DAY2)
        self.assertEqual([r["id"] for r in rows], [hit.pk])
        with self.assertRaises(ValueError):
            export_search_sends(self.salon, "smith", start=DAY2, end=DAY1)

    def test_read_only_no_mutation(self):
        row = self._send("Alice", "Smith", "email", _at(DAY1, 9))
        before = ReminderSend.objects.count()
        export_search_sends_csv(self.salon, "alice")
        self.assertEqual(ReminderSend.objects.count(), before)
        row.refresh_from_db()
        self.assertEqual(row.channel, "email")
