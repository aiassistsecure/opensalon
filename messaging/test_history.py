from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.history import (
    client_send_history,
    counts_by_channel,
    counts_by_day,
    reminder_history_summary,
    sends_for_client,
)
from messaging.models import ReminderSend
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
DAY1 = date(2026, 3, 2)
DAY2 = date(2026, 3, 3)
DAY3 = date(2026, 3, 4)


def _at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=UTC)


class ReminderHistoryBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts"
        )
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        self._n = 0

    def _client(self):
        self._n += 1
        return Client.objects.create(
            salon=self.salon, first_name=f"Client{self._n}",
            last_name="Example", email=f"c{self._n}@example.com",
            phone="555-0100", sms_opt_in=True, email_opt_in=True,
        )

    def _send(self, client, channel, when):
        self._n += 1
        start = timezone.now() + timedelta(days=1)
        appt = Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED,
        )
        return ReminderSend.objects.create(
            appointment=appt, client=client, channel=channel,
            status=ReminderSend.Status.SENT, sent_at=when,
        )


class GroupingTests(ReminderHistoryBase):
    def test_counts_grouped_by_channel(self):
        client = self._client()
        self._send(client, "email", _at(DAY1, 9))
        self._send(client, "email", _at(DAY1, 10))
        self._send(client, "sms", _at(DAY2, 9))
        summary = reminder_history_summary(DAY1, DAY3)
        self.assertEqual(summary.total, 3)
        self.assertEqual(summary.by_channel, {"email": 2, "sms": 1})
        self.assertEqual(summary.count_for("email"), 2)
        self.assertEqual(counts_by_channel(DAY1, DAY3), summary.by_channel)

    def test_counts_grouped_by_local_day(self):
        client = self._client()
        self._send(client, "email", _at(DAY1, 9))
        self._send(client, "sms", _at(DAY1, 23))
        self._send(client, "sms", _at(DAY3, 1))
        summary = reminder_history_summary(DAY1, DAY3)
        # DAY2 has no sends and is zero-filled, not missing.
        self.assertEqual(summary.by_day, {DAY1: 2, DAY2: 0, DAY3: 1})
        self.assertEqual(counts_by_day(DAY1, DAY3), summary.by_day)
        self.assertEqual(
            summary.by_day_by_channel[DAY1], {"email": 1, "sms": 1}
        )
        self.assertEqual(summary.by_date, summary.by_day)

    def test_grouping_uses_local_day_not_utc_day(self):
        client = self._client()
        # 01:00 UTC on DAY2 is 20:00 on DAY1 in America/New_York.
        self._send(client, "email", _at(DAY2, 1))
        with timezone.override(ZoneInfo("America/New_York")):
            summary = reminder_history_summary(DAY1, DAY2)
        self.assertEqual(summary.by_day[DAY1], 1)
        self.assertEqual(summary.by_day[DAY2], 0)


class RangeFilteringTests(ReminderHistoryBase):
    def test_sends_outside_range_are_excluded(self):
        client = self._client()
        self._send(client, "email", _at(DAY1, 9))
        self._send(client, "email", _at(DAY2, 9))
        self._send(client, "sms", _at(DAY3, 9))
        summary = reminder_history_summary(DAY2, DAY2)
        self.assertEqual(summary.total, 1)
        self.assertEqual(summary.by_channel, {"email": 1, "sms": 0})
        self.assertEqual(summary.by_day, {DAY2: 1})

    def test_range_bounds_are_inclusive_whole_days(self):
        client = self._client()
        self._send(client, "email", _at(DAY1, 0))
        self._send(client, "email", _at(DAY2, 23))
        summary = reminder_history_summary(
            date_from=DAY1, date_to=DAY2
        )
        self.assertEqual(summary.total, 2)
        self.assertEqual(summary.start_date, DAY1)
        self.assertEqual(summary.end_date, DAY2)

    def test_reversed_range_raises(self):
        with self.assertRaises(ValueError):
            reminder_history_summary(DAY3, DAY1)


class ClientHistoryTests(ReminderHistoryBase):
    def test_per_client_history_most_recent_first(self):
        alice = self._client()
        bob = self._client()
        oldest = self._send(alice, "email", _at(DAY1, 9))
        self._send(bob, "email", _at(DAY2, 9))
        newest = self._send(alice, "sms", _at(DAY3, 9))
        middle = self._send(alice, "email", _at(DAY2, 10))
        history = client_send_history(alice)
        self.assertEqual(
            [row.id for row in history],
            [newest.id, middle.id, oldest.id],
        )
        self.assertTrue(all(row.client_id == alice.id for row in history))
        # Alias accepts a bare id too.
        self.assertEqual(
            [row.id for row in sends_for_client(alice.id)],
            [row.id for row in history],
        )

    def test_per_client_history_limit(self):
        client = self._client()
        self._send(client, "email", _at(DAY1, 9))
        self._send(client, "email", _at(DAY2, 9))
        self.assertEqual(len(client_send_history(client, limit=1)), 1)


class EmptyCaseTests(ReminderHistoryBase):
    def test_empty_range_is_zeroed_not_none(self):
        summary = reminder_history_summary(DAY1, DAY3)
        self.assertIsNotNone(summary)
        self.assertEqual(summary.total, 0)
        self.assertEqual(summary.by_channel, {"email": 0, "sms": 0})
        self.assertEqual(
            summary.by_day, {DAY1: 0, DAY2: 0, DAY3: 0}
        )
        self.assertEqual(summary.as_dict()["total"], 0)

    def test_client_without_sends_has_empty_history(self):
        client = self._client()
        self.assertEqual(client_send_history(client), [])
        self.assertEqual(client_send_history(None), [])
        self.assertEqual(client_send_history(999999), [])
