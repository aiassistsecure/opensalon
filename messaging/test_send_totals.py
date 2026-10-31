from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.models import ReminderSend
from messaging.send_totals import per_channel_send_totals, send_totals
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
DAY1 = date(2026, 3, 2)
DAY2 = date(2026, 3, 3)
DAY3 = date(2026, 3, 4)


def _at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=UTC)


class SendTotalsBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other Stylist"
        )
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts"
        )
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        self._n = 0

    def _send(self, salon, staff, channel, when, status="sent"):
        self._n += 1
        client = Client.objects.create(
            salon=salon, first_name=f"C{self._n}", last_name="Example",
            email=f"c{self._n}@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True,
        )
        start = timezone.now() + timedelta(days=1)
        appt = Appointment.objects.create(
            client=client, staff_member=staff, service=self.service,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED,
        )
        return ReminderSend.objects.create(
            appointment=appt, client=client, channel=channel,
            status=status, sent_at=when,
        )

    def _own(self, channel, when, status="sent"):
        return self._send(self.salon, self.staff, channel, when, status)


class GroupingTests(SendTotalsBase):
    def test_channel_and_status_grouping(self):
        self._own("email", _at(DAY1, 9))
        self._own("email", _at(DAY1, 10))
        self._own("sms", _at(DAY2, 9))
        result = send_totals(self.salon, DAY1, DAY3)
        self.assertEqual(result.total, 3)
        self.assertEqual(result.salon, self.salon)
        self.assertEqual(result.by_channel, {"email": 2, "sms": 1})
        # Only status that exists on ReminderSend is "sent".
        self.assertEqual(result.by_status, {"sent": 3})
        self.assertEqual(result.status_count("sent"), 3)
        self.assertEqual(
            result.by_channel_by_status,
            {"email": {"sent": 2}, "sms": {"sent": 1}},
        )
        self.assertEqual(result.count_for("sms"), 1)
        self.assertEqual(per_channel_send_totals(
            self.salon, DAY1, DAY3).total, 3)

    def test_per_day_zero_filled(self):
        self._own("email", _at(DAY1, 9))
        self._own("sms", _at(DAY1, 23))
        self._own("sms", _at(DAY3, 1))
        result = send_totals(self.salon, DAY1, DAY3)
        self.assertEqual(result.by_day, {DAY1: 2, DAY2: 0, DAY3: 1})
        self.assertEqual(result.by_date, result.by_day)
        self.assertEqual(
            result.by_day_by_channel[DAY2], {"email": 0, "sms": 0})
        self.assertEqual(
            result.by_day_by_channel[DAY1], {"email": 1, "sms": 1})

    def test_local_day_uses_salon_timezone(self):
        ny = Salon.objects.create(name="NY Salon", timezone="America/New_York")
        staff = StaffMember.objects.create(salon=ny, display_name="NY")
        # 01:00 UTC on DAY2 is 20:00 on DAY1 in America/New_York.
        self._send(ny, staff, "email", _at(DAY2, 1))
        result = send_totals(ny, DAY1, DAY2)
        self.assertEqual(result.by_day, {DAY1: 1, DAY2: 0})


class RangeAndScopeTests(SendTotalsBase):
    def test_range_boundaries_inclusive_whole_days(self):
        self._own("email", _at(DAY1, 0))
        self._own("email", _at(DAY2, 23))
        self._own("email", _at(DAY3, 0))
        result = send_totals(self.salon, date_from=DAY1, date_to=DAY2)
        self.assertEqual(result.total, 2)
        self.assertEqual((result.start_date, result.end_date), (DAY1, DAY2))
        single = send_totals(self.salon, DAY2, DAY2)
        self.assertEqual(single.by_day, {DAY2: 1})

    def test_other_salon_excluded(self):
        self._own("email", _at(DAY1, 9))
        self._send(self.other, self.other_staff, "email", _at(DAY1, 9))
        self._send(self.other, self.other_staff, "sms", _at(DAY1, 10))
        result = send_totals(self.salon, DAY1, DAY3)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.by_channel, {"email": 1, "sms": 0})
        self.assertEqual(send_totals(self.other, DAY1, DAY3).total, 2)

    def test_reversed_range_raises(self):
        with self.assertRaises(ValueError):
            send_totals(self.salon, DAY3, DAY1)


class EmptyAndReadOnlyTests(SendTotalsBase):
    def test_empty_range_zeroed_not_none(self):
        result = send_totals(self.salon, DAY1, DAY3)
        self.assertIsNotNone(result)
        self.assertEqual(result.total, 0)
        self.assertEqual(result.by_channel, {"email": 0, "sms": 0})
        self.assertEqual(result.by_status, {"sent": 0})
        self.assertEqual(result.by_day, {DAY1: 0, DAY2: 0, DAY3: 0})
        self.assertEqual(result.as_dict()["by_day"][DAY2], 0)
        self.assertEqual(send_totals(None, DAY1, DAY2).total, 0)

    def test_read_only_no_mutation_no_new_rows(self):
        row = self._own("email", _at(DAY1, 9))
        before = ReminderSend.objects.count()
        snapshot = (row.channel, row.status, row.sent_at, row.detail)
        send_totals(self.salon, DAY1, DAY3)
        send_totals(self.salon, DAY1, DAY3)
        self.assertEqual(ReminderSend.objects.count(), before)
        row.refresh_from_db()
        self.assertEqual(
            (row.channel, row.status, row.sent_at, row.detail), snapshot)
