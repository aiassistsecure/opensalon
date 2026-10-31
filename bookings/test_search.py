import datetime

from django.test import TestCase

from bookings.models import Appointment
from bookings.search import search_appointments
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
DAY = datetime.date(2026, 11, 2)


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class SearchAppointmentsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two"
        )
        self.alice = Client.objects.create(
            salon=self.salon, first_name="Alice", last_name="Smith"
        )
        self.bob = Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Jones"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        # Created out of start order to prove ordering by start.
        self.late = self._appt(self.alice, self.staff, at(DAY, 14),
                               status=Appointment.Status.BOOKED)
        self.early = self._appt(self.alice, self.staff2, at(DAY, 9),
                                status=Appointment.Status.CONFIRMED)
        self.bob_appt = self._appt(self.bob, self.staff, at(DAY, 11),
                                   status=Appointment.Status.BOOKED)
        self.next_day = self._appt(
            self.bob, self.staff2, at(DAY + datetime.timedelta(days=1), 9),
            status=Appointment.Status.CANCELLED,
        )
        # Snapshot-only appointment: service=None, name in snapshot.
        self.snapshot = Appointment.objects.create(
            client=self.alice, staff_member=self.staff, service=None,
            service_name="Legacy Treatment",
            start=at(DAY, 16), end=at(DAY, 17),
            status=Appointment.Status.BOOKED,
        )
        # Another salon's appointment that matches name/status/staff name.
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Stylist One"
        )
        other_client = Client.objects.create(
            salon=self.other_salon, first_name="Alice", last_name="Smith"
        )
        self.foreign = Appointment.objects.create(
            client=other_client, staff_member=other_staff,
            service=self.service, start=at(DAY, 10), end=at(DAY, 11),
            status=Appointment.Status.BOOKED,
        )

    def _appt(self, client, staff, start, **kw):
        return Appointment.objects.create(
            client=client, staff_member=staff, service=self.service,
            start=start, end=start + datetime.timedelta(hours=1), **kw,
        )

    def results(self, **kw):
        return list(search_appointments(self.salon, **kw))

    def test_no_filters_returns_salon_appointments_ordered_by_start(self):
        self.assertEqual(
            self.results(),
            [self.early, self.bob_appt, self.late, self.snapshot, self.next_day],
        )

    def test_query_matches_first_and_last_name_case_insensitive(self):
        self.assertEqual(self.results(query="alice"),
                         [self.early, self.late, self.snapshot])
        self.assertEqual(self.results(query="SMITH"),
                         [self.early, self.late, self.snapshot])
        self.assertEqual(self.results(query="jon"), [self.bob_appt, self.next_day])
        self.assertEqual(self.results(query="Alice Smith"),
                         [self.early, self.late, self.snapshot])

    def test_query_substring_whitespace_and_no_match(self):
        self.assertEqual(self.results(query="  ali  "),
                         [self.early, self.late, self.snapshot])
        self.assertEqual(self.results(query="no-such"), [])
        self.assertEqual(len(self.results(query="")), 5)
        self.assertEqual(len(self.results(query="   ")), 5)
        self.assertEqual(len(self.results(query=None)), 5)

    def test_date_range_with_datetimes_is_inclusive_on_start(self):
        self.assertEqual(
            self.results(date_from=at(DAY, 11), date_to=at(DAY, 14)),
            [self.bob_appt, self.late],
        )
        self.assertEqual(self.results(date_from=at(DAY, 12)), 
                         [self.late, self.snapshot, self.next_day])
        self.assertEqual(self.results(date_to=at(DAY, 9)), [self.early])

    def test_date_range_with_plain_dates_covers_whole_days(self):
        self.assertEqual(len(self.results(date_from=DAY, date_to=DAY)), 4)
        self.assertEqual(
            self.results(date_from=DAY + datetime.timedelta(days=1)),
            [self.next_day],
        )

    def test_staff_filter_by_instance_and_pk(self):
        self.assertEqual(self.results(staff_member=self.staff),
                         [self.bob_appt, self.late, self.snapshot])
        self.assertEqual(self.results(staff_member=self.staff2.pk),
                         [self.early, self.next_day])

    def test_status_filter_by_string_and_enum(self):
        self.assertEqual(self.results(status="booked"),
                         [self.bob_appt, self.late, self.snapshot])
        self.assertEqual(
            self.results(status=Appointment.Status.CONFIRMED), [self.early]
        )
        self.assertEqual(self.results(status="cancelled"), [self.next_day])

    def test_combined_filters(self):
        self.assertEqual(
            self.results(query="alice", staff_member=self.staff,
                         status="booked", date_from=DAY, date_to=DAY),
            [self.late, self.snapshot],
        )
        self.assertEqual(
            self.results(query="bob", status=Appointment.Status.BOOKED,
                         date_from=at(DAY, 0), date_to=at(DAY, 23)),
            [self.bob_appt],
        )
        self.assertEqual(
            self.results(query="alice", staff_member=self.staff2,
                         status="booked"),
            [],
        )

    def test_snapshot_appointment_searchable_and_does_not_crash(self):
        found = self.results(query="alice")
        self.assertIn(self.snapshot, found)
        for appt in found:
            # The day-book fallback pattern must work on every result.
            name = appt.service.name if appt.service else appt.service_name
            self.assertTrue(name)
        self.assertIsNone(self.snapshot.service)
        self.assertEqual(self.snapshot.service_name, "Legacy Treatment")

    def test_cross_salon_isolation(self):
        self.assertNotIn(self.foreign, self.results())
        self.assertNotIn(self.foreign, self.results(query="alice"))
        self.assertEqual(
            list(search_appointments(self.other_salon, query="alice")),
            [self.foreign],
        )

    def test_returns_queryset(self):
        qs = search_appointments(self.salon)
        self.assertEqual(qs.model, Appointment)
