from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.models import ReminderSend
from messaging.send_search import reminder_send_search, search_sends
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
DAY1 = date(2026, 3, 2)
DAY2 = date(2026, 3, 3)
DAY3 = date(2026, 3, 4)


def _at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=UTC)


class SendSearchBase(TestCase):
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

    def _send(self, first, last, channel, when, salon=None, staff=None,
              status="sent"):
        salon = salon or self.salon
        staff = staff or self.staff
        client = Client.objects.create(
            salon=salon, first_name=first, last_name=last,
            email="c@example.com", phone="555-0100",
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


class SalonScopingTests(SendSearchBase):
    def test_only_own_salon_returned(self):
        own = self._send("Alice", "Smith", "email", _at(DAY1, 9))
        self._send("Alice", "Smith", "email", _at(DAY1, 10),
                   salon=self.other, staff=self.other_staff)
        results = search_sends(self.salon)
        self.assertEqual([r.id for r in results], [own.id])
        self.assertEqual(len(search_sends(self.other)), 1)

    def test_none_salon_is_empty_not_none(self):
        self._send("Alice", "Smith", "email", _at(DAY1, 9))
        self.assertEqual(search_sends(None), [])


class NameFilterTests(SendSearchBase):
    def test_fragment_matches_first_name_case_insensitive(self):
        hit = self._send("Alice", "Smith", "email", _at(DAY1, 9))
        self._send("Bob", "Jones", "email", _at(DAY1, 10))
        results = search_sends(self.salon, "ali")
        self.assertEqual([r.id for r in results], [hit.id])

    def test_fragment_matches_last_name_case_insensitive(self):
        hit = self._send("Alice", "Smith", "sms", _at(DAY1, 9))
        self._send("Bob", "Jones", "sms", _at(DAY1, 10))
        results = search_sends(self.salon, "SMITH")
        self.assertEqual([r.id for r in results], [hit.id])
        self.assertEqual(
            [r.id for r in reminder_send_search(self.salon, "smith")],
            [hit.id],
        )

    def test_fragment_with_no_match_is_empty(self):
        self._send("Alice", "Smith", "email", _at(DAY1, 9))
        self.assertEqual(search_sends(self.salon, "zzz"), [])

    def test_blank_fragment_means_no_name_filter(self):
        self._send("Alice", "Smith", "email", _at(DAY1, 9))
        self._send("Bob", "Jones", "email", _at(DAY1, 10))
        self.assertEqual(len(search_sends(self.salon, "  ")), 2)
        self.assertEqual(len(search_sends(self.salon)), 2)


class ChannelStatusTests(SendSearchBase):
    def test_channel_filter(self):
        self._send("Alice", "Smith", "email", _at(DAY1, 9))
        sms = self._send("Alice", "Smith", "sms", _at(DAY1, 10))
        results = search_sends(self.salon, channel="sms")
        self.assertEqual([r.id for r in results], [sms.id])

    def test_status_filter(self):
        sent = self._send("Alice", "Smith", "email", _at(DAY1, 9))
        self._send("Alice", "Smith", "email", _at(DAY1, 10), status="failed")
        results = search_sends(self.salon, status="sent")
        self.assertEqual([r.id for r in results], [sent.id])
        self.assertEqual(len(search_sends(self.salon, status="failed")), 1)


class DateRangeTests(SendSearchBase):
    def test_range_is_inclusive_whole_days(self):
        self._send("Alice", "Smith", "email", _at(DAY1, 0))
        mid = self._send("Alice", "Smith", "email", _at(DAY2, 23))
        self._send("Alice", "Smith", "email", _at(DAY3, 0))
        results = search_sends(self.salon, start=DAY2, end=DAY2)
        self.assertEqual([r.id for r in results], [mid.id])
        both = search_sends(self.salon, date_from=DAY1, date_to=DAY2)
        self.assertEqual(len(both), 2)

    def test_single_bound_only(self):
        self._send("Alice", "Smith", "email", _at(DAY1, 9))
        self._send("Alice", "Smith", "email", _at(DAY3, 9))
        self.assertEqual(len(search_sends(self.salon, start=DAY2)), 1)
        self.assertEqual(len(search_sends(self.salon, end=DAY2)), 1)

    def test_reversed_range_raises(self):
        with self.assertRaises(ValueError):
            search_sends(self.salon, start=DAY3, end=DAY1)


class OrderingAndCombinationTests(SendSearchBase):
    def test_newest_first_then_id_descending(self):
        oldest = self._send("Alice", "Smith", "email", _at(DAY1, 9))
        tie_low = self._send("Bob", "Jones", "email", _at(DAY2, 9))
        tie_high = self._send("Cara", "Lee", "sms", _at(DAY2, 9))
        results = search_sends(self.salon)
        self.assertEqual(
            [r.id for r in results],
            [tie_high.id, tie_low.id, oldest.id],
        )

    def test_filters_combine_with_and(self):
        hit = self._send("Alice", "Smith", "sms", _at(DAY2, 9))
        self._send("Alice", "Smith", "email", _at(DAY2, 9))
        self._send("Alice", "Jones", "sms", _at(DAY2, 9))
        self._send("Alice", "Smith", "sms", _at(DAY1, 9))
        results = search_sends(
            self.salon, "smith", channel="sms", start=DAY2, end=DAY2
        )
        self.assertEqual([r.id for r in results], [hit.id])

    def test_read_only_no_mutation(self):
        row = self._send("Alice", "Smith", "email", _at(DAY1, 9))
        before = ReminderSend.objects.count()
        search_sends(self.salon, "alice", channel="email")
        self.assertEqual(ReminderSend.objects.count(), before)
        row.refresh_from_db()
        self.assertEqual(row.channel, "email")
