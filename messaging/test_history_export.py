import csv
import io
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.history import client_send_history, reminder_history_summary
from messaging.history_export import (
    CLIENT_HISTORY_FIELDNAMES,
    HISTORY_EXPORT_FIELDNAMES,
    export_client_history,
    export_client_history_csv,
    export_history_summary,
    export_history_summary_csv,
    history_export_csv,
)
from messaging.models import ReminderSend
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
DAY1 = date(2026, 3, 2)
DAY2 = date(2026, 3, 3)
DAY3 = date(2026, 3, 4)


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def _at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=UTC)


class HistoryExportBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self._n = 0

    def _client(self):
        self._n += 1
        return Client.objects.create(
            salon=self.salon, first_name=f"Client{self._n}",
            last_name="Example", email=f"c{self._n}@example.com",
            phone="555-0100", sms_opt_in=True, email_opt_in=True)

    def _send(self, client, channel, when):
        start = timezone.now() + timedelta(days=1)
        appt = Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)
        return ReminderSend.objects.create(
            appointment=appt, client=client, channel=channel,
            status=ReminderSend.Status.SENT, sent_at=when)


class SummaryHeaderAndRowTests(HistoryExportBase):
    def test_header_and_rows_match_service_output(self):
        client = self._client()
        self._send(client, "email", _at(DAY1, 9))
        self._send(client, "email", _at(DAY1, 10))
        self._send(client, "sms", _at(DAY3, 9))
        text = export_history_summary_csv(DAY1, DAY3)
        self.assertEqual(
            text.splitlines()[0], ",".join(HISTORY_EXPORT_FIELDNAMES))
        summary = reminder_history_summary(DAY1, DAY3)
        expected = [
            {"start_date": DAY1.isoformat(), "end_date": DAY3.isoformat(),
             "date": day.isoformat(), "channel": channel,
             "count": str(summary.by_day_by_channel[day][channel])}
            for day in (DAY1, DAY2, DAY3)
            for channel in ("email", "sms")]
        rows = _rows(text)
        self.assertEqual(rows, expected)
        self.assertTrue(
            all(list(r) == HISTORY_EXPORT_FIELDNAMES for r in rows))
        self.assertEqual(
            sum(int(r["count"]) for r in rows), summary.total)

    def test_list_agrees_with_csv_and_alias(self):
        self._send(self._client(), "sms", _at(DAY2, 9))
        rows = export_history_summary(DAY1, DAY3)
        parsed = [
            {**r, "count": int(r["count"])}
            for r in _rows(export_history_summary_csv(DAY1, DAY3))]
        self.assertEqual(parsed, rows)
        self.assertEqual(
            history_export_csv(DAY1, DAY3),
            export_history_summary_csv(DAY1, DAY3))

    def test_reversed_range_raises_as_service_does(self):
        with self.assertRaises(ValueError):
            export_history_summary_csv(DAY3, DAY1)


class SummaryEmptyTests(HistoryExportBase):
    def test_empty_range_is_zero_filled_not_missing(self):
        rows = export_history_summary(DAY1, DAY2)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r["count"] == 0 for r in rows))
        self.assertEqual(
            reminder_history_summary(DAY1, DAY2).total, 0)
        parsed = _rows(export_history_summary_csv(DAY1, DAY2))
        self.assertEqual([int(r["count"]) for r in parsed], [0, 0, 0, 0])


class ClientHistoryTests(HistoryExportBase):
    def test_header_and_rows_match_service_output(self):
        alice = self._client()
        bob = self._client()
        oldest = self._send(alice, "email", _at(DAY1, 9))
        self._send(bob, "email", _at(DAY2, 9))
        newest = self._send(alice, "sms", _at(DAY3, 9))
        text = export_client_history_csv(alice)
        self.assertEqual(
            text.splitlines()[0], ",".join(CLIENT_HISTORY_FIELDNAMES))
        rows = _rows(text)
        service_rows = client_send_history(alice)
        self.assertEqual(
            [int(r["id"]) for r in rows], [s.id for s in service_rows])
        self.assertEqual(
            [int(r["id"]) for r in rows], [newest.id, oldest.id])
        for row, send in zip(rows, service_rows):
            self.assertEqual(list(row), CLIENT_HISTORY_FIELDNAMES)
            self.assertEqual(int(row["appointment_id"]), send.appointment_id)
            self.assertEqual(int(row["client_id"]), alice.pk)
            self.assertEqual(row["channel"], send.channel)
            self.assertEqual(row["status"], send.status)
            self.assertEqual(row["sent_at"], send.sent_at.isoformat())
        parsed = [
            {**r, "id": int(r["id"]),
             "appointment_id": int(r["appointment_id"]),
             "client_id": int(r["client_id"])}
            for r in rows]
        self.assertEqual(parsed, export_client_history(alice))

    def test_empty_client_history_is_header_only(self):
        client = self._client()
        header = ",".join(CLIENT_HISTORY_FIELDNAMES) + "\n"
        self.assertEqual(export_client_history(client), [])
        self.assertEqual(export_client_history_csv(client), header)
        self.assertEqual(export_client_history_csv(None), header)


class ReadOnlyTests(HistoryExportBase):
    def test_export_mutates_nothing(self):
        client = self._client()
        self._send(client, "email", _at(DAY1, 9))
        before = ReminderSend.objects.count()
        export_history_summary_csv(DAY1, DAY3)
        export_client_history_csv(client)
        self.assertEqual(ReminderSend.objects.count(), before)
