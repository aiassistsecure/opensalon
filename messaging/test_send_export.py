import csv
import io
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.models import ReminderSend
from messaging.send_export import (
    EXPORT_FIELDNAMES,
    RECORD_FIELDNAMES,
    export_send_totals,
    export_send_totals_csv,
    export_sends,
    export_sends_csv,
    send_export_row,
)
from messaging.send_totals import send_totals
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
DAY1 = date(2026, 3, 2)
DAY2 = date(2026, 3, 3)
DAY3 = date(2026, 3, 4)


def _at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=UTC)


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


class SendExportBase(TestCase):
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
        self._n = 0

    def _send(self, salon, staff, channel, when, detail=""):
        self._n += 1
        client = Client.objects.create(
            salon=salon, first_name=f"C{self._n}", last_name="Example",
            email=f"c{self._n}@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True)
        start = timezone.now() + timedelta(days=1)
        appt = Appointment.objects.create(
            client=client, staff_member=staff, service=self.service,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)
        return ReminderSend.objects.create(
            appointment=appt, client=client, channel=channel,
            status="sent", sent_at=when, detail=detail)

    def _own(self, channel, when, detail=""):
        return self._send(self.salon, self.staff, channel, when, detail)


class TotalsExportTests(SendExportBase):
    def test_rows_verbatim_from_send_totals(self):
        self._own("email", _at(DAY1, 9))
        self._own("email", _at(DAY1, 10))
        self._own("sms", _at(DAY2, 9))
        totals = send_totals(self.salon, DAY1, DAY3)
        rows = export_send_totals(self.salon, DAY1, DAY3)
        self.assertEqual(list(rows[0]), EXPORT_FIELDNAMES)
        expected = [
            {"salon_id": self.salon.pk, "date": day.isoformat(),
             "channel": channel,
             "count": totals.by_day_by_channel[day][channel]}
            for day in (DAY1, DAY2, DAY3)
            for channel in ("email", "sms")
        ]
        self.assertEqual(rows, expected)
        self.assertEqual(sum(r["count"] for r in rows), totals.total)

    def test_csv_agrees_with_list_and_single_day_default(self):
        self._own("sms", _at(DAY2, 9))
        text = export_send_totals_csv(self.salon, DAY2)
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        parsed = [
            {**r, "salon_id": int(r["salon_id"]), "count": int(r["count"])}
            for r in _rows(text)
        ]
        self.assertEqual(parsed, export_send_totals(self.salon, DAY2))

    def test_empty_and_reversed_are_header_only(self):
        self.assertEqual(export_send_totals(self.salon, DAY1, DAY3),
                         [{"salon_id": self.salon.pk, "date": d.isoformat(),
                           "channel": c, "count": 0}
                          for d in (DAY1, DAY2, DAY3)
                          for c in ("email", "sms")])
        self.assertEqual(export_send_totals(self.salon, DAY3, DAY1), [])
        self.assertEqual(export_send_totals(None, DAY1), [])
        self.assertEqual(export_send_totals_csv(self.salon, DAY3, DAY1),
                         ",".join(EXPORT_FIELDNAMES) + "\n")

    def test_other_salon_excluded(self):
        self._own("email", _at(DAY1, 9))
        self._send(self.other, self.other_staff, "email", _at(DAY1, 9))
        rows = export_send_totals(self.salon, DAY1, DAY1)
        self.assertEqual(sum(r["count"] for r in rows), 1)


class RecordExportTests(SendExportBase):
    def test_record_rows_only_real_fields_oldest_first(self):
        later = self._own("sms", _at(DAY2, 9), detail="ref-2")
        earlier = self._own("email", _at(DAY1, 9))
        rows = export_sends(self.salon, DAY1, DAY3)
        self.assertEqual([r["id"] for r in rows], [earlier.pk, later.pk])
        self.assertEqual(list(rows[0]), RECORD_FIELDNAMES)
        self.assertEqual(rows[0], send_export_row(earlier))
        self.assertEqual(rows[1]["detail"], "ref-2")
        self.assertEqual(rows[1]["salon_id"], self.salon.pk)
        self.assertEqual(rows[1]["sent_at"], later.sent_at.isoformat())
        for forbidden in ("email", "phone", "first_name"):
            self.assertNotIn(forbidden, rows[0])

    def test_record_csv_agrees_and_empty_header_only(self):
        self._own("email", _at(DAY1, 9))
        text = export_sends_csv(self.salon, DAY1, DAY3)
        self.assertEqual(text.splitlines()[0], ",".join(RECORD_FIELDNAMES))
        self.assertEqual(len(_rows(text)), 1)
        self.assertEqual(export_sends(self.salon, DAY3, DAY1), [])
        self.assertEqual(export_sends_csv(self.salon, DAY3, DAY1),
                         ",".join(RECORD_FIELDNAMES) + "\n")

    def test_read_only_no_mutation(self):
        row = self._own("email", _at(DAY1, 9))
        before = ReminderSend.objects.count()
        export_send_totals_csv(self.salon, DAY1, DAY3)
        export_sends_csv(self.salon, DAY1, DAY3)
        self.assertEqual(ReminderSend.objects.count(), before)
        row.refresh_from_db()
        self.assertEqual(row.channel, "email")
