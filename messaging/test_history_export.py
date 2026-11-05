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


class SummarySalonScopeTests(HistoryExportBase):
    def _other_send(self, channel, when):
        other_salon = Salon.objects.create(name="Other Salon")
        other_staff = StaffMember.objects.create(
            salon=other_salon, display_name="Other Stylist")
        other_category = ServiceCategory.objects.create(
            salon=other_salon, name="Other Haircuts")
        other_service = Service.objects.create(
            category=other_category, name="Other Haircut",
            service_minutes=45)
        client = Client.objects.create(
            salon=other_salon, first_name="Other", last_name="Example",
            email="other@example.com", phone="555-0200",
            sms_opt_in=True, email_opt_in=True)
        start = timezone.now() + timedelta(days=1)
        appt = Appointment.objects.create(
            client=client, staff_member=other_staff,
            service=other_service, start=start,
            end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)
        return ReminderSend.objects.create(
            appointment=appt, client=client, channel=channel,
            status=ReminderSend.Status.SENT, sent_at=when)

    def test_scoped_export_excludes_other_salon_unscoped_includes(self):
        self._send(self._client(), "email", _at(DAY1, 9))
        self._other_send("sms", _at(DAY1, 10))
        unscoped = export_history_summary(DAY1, DAY1)
        self.assertEqual(sum(r["count"] for r in unscoped), 2)
        scoped = export_history_summary(DAY1, DAY1, salon=self.salon)
        self.assertEqual(sum(r["count"] for r in scoped), 1)
        self.assertEqual(
            [r["count"] for r in scoped if r["channel"] == "email"], [1])
        self.assertEqual(
            export_history_summary_csv(DAY1, DAY1, salon=self.salon),
            export_history_summary_csv(
                DAY1, DAY1, salon_id=self.salon.pk))
        parsed = _rows(export_history_summary_csv(
            DAY1, DAY1, salon=self.salon))
        self.assertEqual(sum(int(r["count"]) for r in parsed), 1)


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


class ClientHistoryWindowTests(HistoryExportBase):
    def setUp(self):
        super().setUp()
        self.client = self._client()
        self.oldest = self._send(self.client, "email", _at(DAY1, 9))
        self.middle = self._send(self.client, "sms", _at(DAY2, 9))
        self.newest = self._send(self.client, "email", _at(DAY3, 9))

    def _ids(self, rows):
        return [r["id"] for r in rows]

    def test_default_window_is_unbounded_and_unchanged(self):
        self.assertEqual(
            export_client_history(self.client),
            export_client_history(self.client, start=None, end=None))
        self.assertEqual(
            export_client_history_csv(self.client),
            export_client_history_csv(self.client, start=None, end=None))

    def test_window_filters_on_sent_at(self):
        self.assertEqual(
            self._ids(export_client_history(
                self.client, start=DAY2, end=DAY3)),
            [self.newest.id, self.middle.id])
        self.assertEqual(
            self._ids(export_client_history(self.client, start=DAY2)),
            [self.newest.id, self.middle.id])
        self.assertEqual(
            self._ids(export_client_history(self.client, end=DAY2)),
            [self.middle.id, self.oldest.id])

    def test_date_end_includes_whole_end_day(self):
        late = self._send(self.client, "sms", _at(DAY2, 23))
        self.assertEqual(
            self._ids(export_client_history(
                self.client, start=DAY2, end=DAY2)),
            [late.id, self.middle.id])

    def test_datetime_bounds_are_used_as_given(self):
        self.assertEqual(
            self._ids(export_client_history(
                self.client, start=_at(DAY2, 10), end=_at(DAY3, 10))),
            [self.newest.id])

    def test_window_applies_before_limit(self):
        rows = export_client_history(
            self.client, limit=1, start=DAY1, end=DAY2)
        self.assertEqual(self._ids(rows), [self.middle.id])

    def test_csv_agrees_with_list_for_window(self):
        parsed = [
            {**r, "id": int(r["id"]),
             "appointment_id": int(r["appointment_id"]),
             "client_id": int(r["client_id"])}
            for r in _rows(export_client_history_csv(
                self.client, start=DAY2, end=DAY3))]
        self.assertEqual(
            parsed,
            export_client_history(self.client, start=DAY2, end=DAY3))

    def test_empty_window_is_header_only(self):
        header = ",".join(CLIENT_HISTORY_FIELDNAMES) + "\n"
        self.assertEqual(
            export_client_history(
                self.client, start=date(2027, 1, 1), end=date(2027, 1, 2)),
            [])
        self.assertEqual(
            export_client_history_csv(
                self.client, start=date(2027, 1, 1), end=date(2027, 1, 2)),
            header)


class ClientHistoryChannelTests(HistoryExportBase):
    def setUp(self):
        super().setUp()
        self.client = self._client()
        self.oldest = self._send(self.client, "email", _at(DAY1, 9))
        self.middle = self._send(self.client, "sms", _at(DAY2, 9))
        self.newest = self._send(self.client, "email", _at(DAY3, 9))

    def _ids(self, rows):
        return [r["id"] for r in rows]

    def test_channel_filter_dict_and_csv(self):
        self.assertEqual(
            self._ids(export_client_history(self.client, channel="email")),
            [self.newest.id, self.oldest.id])
        self.assertEqual(
            self._ids(export_client_history(self.client, channel="sms")),
            [self.middle.id])
        parsed = _rows(export_client_history_csv(
            self.client, channel="sms"))
        self.assertEqual([int(r["id"]) for r in parsed], [self.middle.id])
        self.assertTrue(all(r["channel"] == "sms" for r in parsed))

    def test_channel_default_none_is_byte_identical(self):
        self.assertEqual(
            export_client_history(self.client),
            export_client_history(self.client, channel=None))
        self.assertEqual(
            export_client_history_csv(self.client),
            export_client_history_csv(self.client, channel=None))

    def test_channel_filter_exact_no_case_folding(self):
        self.assertEqual(
            export_client_history(self.client, channel="EMAIL"), [])
        self.assertEqual(
            export_client_history(self.client, channel="Sms"), [])

    def test_channel_filter_unknown_channel_is_empty(self):
        header = ",".join(CLIENT_HISTORY_FIELDNAMES) + "\n"
        self.assertEqual(
            export_client_history(self.client, channel="pigeon"), [])
        self.assertEqual(
            export_client_history_csv(self.client, channel="pigeon"),
            header)

    def test_channel_composes_with_window(self):
        self.assertEqual(
            self._ids(export_client_history(
                self.client, start=DAY2, end=DAY3, channel="email")),
            [self.newest.id])
        self.assertEqual(
            self._ids(export_client_history(
                self.client, start=DAY1, end=DAY2, channel="email")),
            [self.oldest.id])

    def test_channel_applies_before_limit(self):
        rows = export_client_history(
            self.client, limit=1, channel="sms")
        self.assertEqual(self._ids(rows), [self.middle.id])

    def test_channel_is_keyword_only(self):
        with self.assertRaises(TypeError):
            export_client_history(
                self.client, None, None, None, "email")
        with self.assertRaises(TypeError):
            export_client_history_csv(
                self.client, None, None, None, "email")


class ReadOnlyTests(HistoryExportBase):
    def test_export_mutates_nothing(self):
        client = self._client()
        self._send(client, "email", _at(DAY1, 9))
        before = ReminderSend.objects.count()
        export_history_summary_csv(DAY1, DAY3)
        export_client_history_csv(client)
        self.assertEqual(ReminderSend.objects.count(), before)
