from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from insights.popularity import ServicePopularity, service_popularity
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)


class ServicePopularityTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other Stylist"
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="C", last_name="Test"
        )
        self.other_client = Client.objects.create(
            salon=self.other, first_name="Other", last_name="Client"
        )
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair"
        )
        self.cut = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        self.colour = Service.objects.create(
            category=category, name="Colour", service_minutes=90
        )

    def _appt(self, *, service=None, service_name="", day_offset=0,
              hour=10, staff=None, client=None,
              status=Appointment.Status.COMPLETED):
        start = datetime(2026, 11, 2, hour, 0, tzinfo=UTC) + timedelta(
            days=day_offset
        )
        return Appointment.objects.create(
            client=client or self.client,
            staff_member=staff or self.staff,
            service=service, service_name=service_name,
            start=start, end=start + timedelta(minutes=45),
            status=status,
        )

    def test_counts_split_by_status_and_ranked_by_completed(self):
        for i in range(3):
            self._appt(service=self.cut, day_offset=i)
        self._appt(service=self.cut, status=Appointment.Status.BOOKED,
                   day_offset=3)
        self._appt(service=self.cut, day_offset=4,
                   status=Appointment.Status.CANCELLED)
        self._appt(service=self.cut, day_offset=5,
                   status=Appointment.Status.NO_SHOW)
        self._appt(service=self.colour)
        self._appt(service=self.colour, day_offset=1,
                   status=Appointment.Status.CONFIRMED)
        self._appt(service=self.colour, day_offset=2,
                   status=Appointment.Status.IN_SERVICE)
        rows = service_popularity(self.salon, START, END)
        self.assertEqual([r.service_name for r in rows],
                         ["Haircut", "Colour"])
        cut, colour = rows
        self.assertIsInstance(cut, ServicePopularity)
        self.assertEqual(cut.service, self.cut)
        self.assertEqual(cut.service_id, self.cut.pk)
        self.assertEqual(cut.completed_count, 3)
        self.assertEqual(cut.booked_count, 1)
        self.assertEqual(cut.cancelled_no_show_count, 2)
        self.assertEqual(cut.cancelled_count, 1)
        self.assertEqual(cut.no_show_count, 1)
        self.assertEqual(cut.total_count, 6)
        self.assertEqual(colour.completed_count, 1)
        self.assertEqual(colour.booked_count, 2)  # confirmed+in_service
        self.assertEqual(colour.cancelled_no_show_count, 0)
        self.assertEqual(colour.total_count, 3)

    def test_snapshot_name_when_no_service_and_unknown_fallback(self):
        self._appt(service_name="Legacy Trim")
        self._appt(service_name="Legacy Trim", day_offset=1,
                   status=Appointment.Status.BOOKED)
        self._appt(day_offset=2)  # no service, no snapshot
        rows = service_popularity(self.salon, START, END)
        by_name = {r.service_name: r for r in rows}
        self.assertEqual(by_name["Legacy Trim"].completed_count, 1)
        self.assertEqual(by_name["Legacy Trim"].booked_count, 1)
        self.assertIsNone(by_name["Legacy Trim"].service)
        self.assertIsNone(by_name["Legacy Trim"].service_id)
        self.assertEqual(by_name["Unknown service"].total_count, 1)

    def test_fk_name_wins_over_snapshot(self):
        self._appt(service=self.cut, service_name="Stale Snapshot")
        rows = service_popularity(self.salon, START, END)
        self.assertEqual([r.service_name for r in rows], ["Haircut"])

    def test_bounds_inclusive_other_salon_excluded_and_read_only(self):
        self._appt(service=self.cut, day_offset=0)
        self._appt(service=self.cut, day_offset=6)
        self._appt(service=self.cut, day_offset=7)
        self._appt(service=self.cut, day_offset=-1)
        self._appt(service=self.cut, staff=self.other_staff,
                   client=self.other_client)
        before = Appointment.objects.count()
        rows = service_popularity(self.salon, START, END)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].total_count, 2)
        self.assertEqual(Appointment.objects.count(), before)

    def test_empty_and_reversed_ranges_return_empty_list(self):
        self.assertEqual(service_popularity(self.salon, START, END), [])
        self.assertEqual(service_popularity(self.salon, END, START), [])

    def test_tie_break_total_then_name(self):
        self._appt(service=self.colour)
        self._appt(service=self.colour, day_offset=1,
                   status=Appointment.Status.BOOKED)
        self._appt(service=self.cut)
        rows = service_popularity(self.salon, START, END)
        # Both 1 completed; Colour wins on total (2 vs 1).
        self.assertEqual([r.service_name for r in rows],
                         ["Colour", "Haircut"])

    def test_days_judged_in_salon_timezone(self):
        ny = Salon.objects.create(name="NY", timezone="America/New_York")
        staff = StaffMember.objects.create(salon=ny, display_name="NY")
        client = Client.objects.create(
            salon=ny, first_name="Local", last_name="Time"
        )
        start = datetime(2026, 11, 3, 1, 30, tzinfo=UTC)
        Appointment.objects.create(
            client=client, staff_member=staff, service=self.cut,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.COMPLETED,
        )
        nov2 = service_popularity(ny, date(2026, 11, 2), date(2026, 11, 2))
        nov3 = service_popularity(ny, date(2026, 11, 3), date(2026, 11, 3))
        self.assertEqual(nov2[0].completed_count, 1)
        self.assertEqual(nov3, [])

    def test_keyword_alias_bounds(self):
        self._appt(service=self.cut)
        rows = service_popularity(
            self.salon, start_date=START, end_date=END
        )
        self.assertEqual(rows[0].total_count, 1)
