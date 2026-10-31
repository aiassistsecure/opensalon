from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from insights.retention import Retention, repeat_visit_retention
from saloncore.models import Salon
from team.models import StaffMember

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)  # Monday
END = date(2026, 11, 8)  # Sunday


class RepeatVisitRetentionTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other Stylist"
        )
        self.clients = [
            Client.objects.create(
                salon=self.salon, first_name=f"C{i}", last_name="Test"
            )
            for i in range(5)
        ]
        self.other_client = Client.objects.create(
            salon=self.other, first_name="Other", last_name="Client"
        )

    def _appt(self, client, *, day_offset=0, hour=10, staff=None,
              status=Appointment.Status.COMPLETED):
        start = datetime(2026, 11, 2, hour, 0, tzinfo=UTC) + timedelta(
            days=day_offset
        )
        return Appointment.objects.create(
            client=client, staff_member=staff or self.staff,
            start=start, end=start + timedelta(minutes=45),
            status=status,
        )

    def test_counts_repeat_rate_and_average(self):
        a, b, c = self.clients[0], self.clients[1], self.clients[2]
        for offset in (0, 2, 4):
            self._appt(a, day_offset=offset)
        self._appt(b, day_offset=1)
        self._appt(c, day_offset=1)
        self._appt(c, day_offset=3, hour=14)
        result = repeat_visit_retention(self.salon, START, END)
        self.assertIsInstance(result, Retention)
        self.assertEqual(result.start_date, START)
        self.assertEqual(result.end_date, END)
        self.assertEqual(result.active_clients, 3)
        self.assertEqual(result.active_client_count, 3)
        self.assertEqual(result.repeat_clients, 2)
        self.assertEqual(result.clients_with_at_least_two_visits, 2)
        self.assertEqual(result.total_visits, 6)
        self.assertAlmostEqual(result.repeat_rate, 2 / 3)
        self.assertAlmostEqual(result.average_visits_per_active_client, 2.0)
        self.assertAlmostEqual(result.average_visits, 2.0)

    def test_only_completed_counts_cancelled_no_show_and_pending_do_not(self):
        a, b = self.clients[0], self.clients[1]
        self._appt(a)
        self._appt(a, day_offset=1, status=Appointment.Status.CANCELLED)
        self._appt(a, day_offset=2, status=Appointment.Status.NO_SHOW)
        for status in (Appointment.Status.BOOKED,
                       Appointment.Status.CONFIRMED,
                       Appointment.Status.ARRIVED,
                       Appointment.Status.IN_SERVICE,
                       Appointment.Status.CANCELLED,
                       Appointment.Status.NO_SHOW):
            self._appt(b, day_offset=1, status=status)
        result = repeat_visit_retention(self.salon, START, END)
        self.assertEqual(result.active_clients, 1)
        self.assertEqual(result.repeat_clients, 0)
        self.assertEqual(result.total_visits, 1)
        self.assertEqual(result.repeat_rate, 0.0)
        self.assertEqual(result.average_visits_per_active_client, 1.0)

    def test_bounds_inclusive_and_visits_outside_range_do_not_make_repeat(self):
        a = self.clients[0]
        self._appt(a, day_offset=0)  # start bound
        self._appt(a, day_offset=6)  # end bound
        self._appt(a, day_offset=7)  # after range
        self._appt(a, day_offset=-1)  # before range
        b = self.clients[1]
        self._appt(b, day_offset=3)  # one inside
        self._appt(b, day_offset=10)  # one outside -> not a repeat here
        result = repeat_visit_retention(self.salon, START, END)
        self.assertEqual(result.active_clients, 2)
        self.assertEqual(result.repeat_clients, 1)
        self.assertEqual(result.total_visits, 3)

    def test_other_salon_excluded_and_read_only(self):
        self._appt(self.other_client, staff=self.other_staff)
        self._appt(self.other_client, staff=self.other_staff, day_offset=1)
        self._appt(self.clients[0])
        before = Appointment.objects.count()
        result = repeat_visit_retention(self.salon, START, END)
        self.assertEqual(result.active_clients, 1)
        self.assertEqual(result.total_visits, 1)
        self.assertEqual(Appointment.objects.count(), before)

    def test_empty_and_reversed_ranges_return_zeroes(self):
        for start, end in ((START, END), (END, START)):
            result = repeat_visit_retention(self.salon, start, end)
            self.assertEqual(result.active_clients, 0)
            self.assertEqual(result.repeat_clients, 0)
            self.assertEqual(result.total_visits, 0)
            self.assertEqual(result.repeat_rate, 0.0)
            self.assertEqual(result.average_visits_per_active_client, 0.0)

    def test_days_judged_in_salon_timezone(self):
        ny = Salon.objects.create(name="NY", timezone="America/New_York")
        staff = StaffMember.objects.create(salon=ny, display_name="NY")
        client = Client.objects.create(
            salon=ny, first_name="Local", last_name="Time"
        )
        # 2026-11-03 01:30 UTC is 2026-11-02 20:30 in New York (EST).
        start = datetime(2026, 11, 3, 1, 30, tzinfo=UTC)
        Appointment.objects.create(
            client=client, staff_member=staff, start=start,
            end=start + timedelta(minutes=45),
            status=Appointment.Status.COMPLETED,
        )
        nov2 = repeat_visit_retention(ny, date(2026, 11, 2),
                                      date(2026, 11, 2))
        nov3 = repeat_visit_retention(ny, date(2026, 11, 3),
                                      date(2026, 11, 3))
        self.assertEqual(nov2.total_visits, 1)
        self.assertEqual(nov3.total_visits, 0)

    def test_keyword_alias_bounds(self):
        self._appt(self.clients[0])
        result = repeat_visit_retention(
            self.salon, start_date=START, end_date=END
        )
        self.assertEqual(result.total_visits, 1)
