import csv
import io
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.models import ReminderSend
from messaging.send_totals import send_totals
from messaging.send_totals_export import (
    TOTALS_EXPORT_FIELDNAMES,
    export_send_totals_summary,
    export_send_totals_summary_csv,
    send_totals_export_csv,
)
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


class SendTotalsExportBase(TestCase):
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

    def _send(self, salon, staff, channel, when):
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
            status="sent", sent_at=when)

    def _own(self, channel, when):
        return self._send(self.salon, self.staff, channel, when)


class HeaderTests(SendTotalsExportBase):
    def test_csv_header_and_row_keys(self):
        text = export_send_totals_summary_csv(self.salon, DAY1, DAY3)
        self.assertEqual(
            text.splitlines()[0], ",".join(TOTALS_EXPORT_FIELDNAMES))
        rows = export_send_totals_summary(self.salon, DAY1, DAY3)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(list(row), TOTALS_EXPORT_FIELDNAMES)
        parsed = _rows(text)
        self.assertEqual(list(parsed[0]), TOTALS_EXPORT_FIELDNAMES)


class TotalsMatchServiceTests(SendTotalsExportBase):
    def test_rows_match_send_totals_verbatim(self):
        self._own("email", _at(DAY1, 9))
        self._own("email", _at(DAY1, 10))
        self._own("sms", _at(DAY2, 9))
        self._send(self.other, self.other_staff, "email", _at(DAY1, 9))
        totals = send_totals(self.salon, DAY1, DAY3)
        rows = export_send_totals_summary(self.salon, DAY1, DAY3)
        expected = [
            {"salon_id": self.salon.pk,
             "start_date": DAY1.isoformat(), "end_date": DAY3.isoformat(),
             "channel": channel, "status": status,
             "count": totals.by_channel_by_status[channel][status]}
            for channel in ("email", "sms")
            for status in ("sent",)
        ]
        self.assertEqual(rows, expected)
        self.assertEqual(sum(r["count"] for r in rows), totals.total)
        self.assertEqual(totals.total, 3)

    def test_csv_agrees_with_list_and_alias(self):
        self._own("sms", _at(DAY2, 9))
        text = export_send_totals_summary_csv(self.salon, DAY1, DAY3)
        parsed = [
            {**r, "salon_id": int(r["salon_id"]), "count": int(r["count"])}
            for r in _rows(text)
        ]
        self.assertEqual(
            parsed, export_send_totals_summary(self.salon, DAY1, DAY3))
        self.assertEqual(
            send_totals_export_csv(self.salon, DAY1, DAY3), text)


class EmptyPeriodTests(SendTotalsExportBase):
    def test_empty_period_zero_rows_not_none(self):
        rows = export_send_totals_summary(self.salon, DAY1, DAY3)
        self.assertEqual(
            rows,
            [{"salon_id": self.salon.pk,
              "start_date": DAY1.isoformat(), "end_date": DAY3.isoformat(),
              "channel": channel, "status": "sent", "count": 0}
             for channel in ("email", "sms")])
        self.assertEqual(sum(r["count"] for r in rows), 0)
        parsed = _rows(export_send_totals_summary_csv(self.salon, DAY1, DAY3))
        self.assertEqual([int(r["count"]) for r in parsed], [0, 0])

    def test_no_export_ranges_are_header_only(self):
        header = ",".join(TOTALS_EXPORT_FIELDNAMES) + "\n"
        self.assertEqual(export_send_totals_summary(self.salon, DAY3, DAY1), [])
        self.assertEqual(export_send_totals_summary(None, DAY1), [])
        self.assertEqual(
            export_send_totals_summary_csv(self.salon, DAY3, DAY1), header)

    def test_read_only_no_mutation(self):
        row = self._own("email", _at(DAY1, 9))
        before = ReminderSend.objects.count()
        export_send_totals_summary_csv(self.salon, DAY1, DAY3)
        self.assertEqual(ReminderSend.objects.count(), before)
        row.refresh_from_db()
        self.assertEqual(row.channel, "email")
