import datetime

from django.test import TestCase

from bookings.client_history import (
    client_appointments,
    past_and_upcoming,
    past_appointments,
    upcoming_appointments,
)
from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def at(day_offset, hour, minute=0):
    return NOW + datetime.timedelta(days=day_offset, hours=hour - 12, minutes=minute)


class ClientHistoryBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        self.other = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )

    def _appt(self, start, client=None, **kw):
        return Appointment.objects.create(
            client=client or self.client,
            staff_member=self.staff,
            service=self.service,
            start=start,
            end=start + datetime.timedelta(minutes=45),
            **kw,
        )


class ClientAppointmentsTests(ClientHistoryBase):
    def test_full_history_newest_first(self):
        old = self._appt(at(-10, 9))
        recent = self._appt(at(-1, 9))
        middle = self._appt(at(-5, 9))
        future = self._appt(at(3, 9))
        result = list(client_appointments(self.client))
        self.assertEqual(result, [future, recent, middle, old])

    def test_never_returns_another_clients_appointments(self):
        mine = self._appt(at(-1, 9))
        self._appt(at(-1, 10), client=self.other)
        self._appt(at(1, 9), client=self.other)
        self.assertEqual(list(client_appointments(self.client)), [mine])
        self.assertEqual(
            {a.client_id for a in client_appointments(self.client)},
            {self.client.pk},
        )

    def test_other_salon_client_also_excluded(self):
        other_salon = Salon.objects.create(name="Other Salon", timezone="UTC")
        outsider = Client.objects.create(
            salon=other_salon, first_name="Out", last_name="Sider"
        )
        self._appt(at(-1, 9), client=outsider)
        self.assertEqual(list(client_appointments(self.client)), [])

    def test_empty_for_client_without_appointments(self):
        self._appt(at(-1, 9), client=self.other)
        self.assertEqual(list(client_appointments(self.client)), [])

    def test_all_statuses_included_in_history(self):
        for status in Appointment.Status.values:
            self._appt(at(-1, 9), status=status)
        self.assertEqual(
            client_appointments(self.client).count(),
            len(Appointment.Status.values),
        )

    def test_same_start_tie_break_is_deterministic(self):
        first = self._appt(at(-1, 9))
        second = self._appt(at(-1, 9))
        # Newest-first ordering falls back to -pk on equal starts.
        self.assertEqual(
            list(client_appointments(self.client)), [second, first]
        )

    def test_upcoming_only_excludes_past_and_orders_soonest_first(self):
        self._appt(at(-1, 9))
        later = self._appt(at(5, 9))
        sooner = self._appt(at(1, 9))
        result = list(
            client_appointments(self.client, upcoming_only=True, now=NOW)
        )
        self.assertEqual(result, [sooner, later])

    def test_upcoming_only_never_returns_another_client(self):
        self._appt(at(1, 9), client=self.other)
        self.assertEqual(
            list(client_appointments(self.client, upcoming_only=True, now=NOW)),
            [],
        )


class PastUpcomingSplitTests(ClientHistoryBase):
    def test_past_newest_first_upcoming_soonest_first(self):
        old = self._appt(at(-10, 9))
        recent = self._appt(at(-1, 9))
        sooner = self._appt(at(1, 9))
        later = self._appt(at(5, 9))
        self.assertEqual(
            list(past_appointments(self.client, now=NOW)), [recent, old]
        )
        self.assertEqual(
            list(upcoming_appointments(self.client, now=NOW)), [sooner, later]
        )

    def test_exactly_now_counts_as_upcoming(self):
        at_now = self._appt(NOW)
        just_before = self._appt(NOW - datetime.timedelta(minutes=1))
        self.assertEqual(
            list(upcoming_appointments(self.client, now=NOW)), [at_now]
        )
        self.assertEqual(
            list(past_appointments(self.client, now=NOW)), [just_before]
        )

    def test_split_covers_every_appointment_exactly_once(self):
        created = [self._appt(at(d, 9)) for d in (-3, -1, 0, 2, 7)]
        # d=0 is at 09:00 on NOW's day, i.e. before NOW (12:00).
        past, upcoming = past_and_upcoming(self.client, now=NOW)
        past_ids = [a.pk for a in past]
        upcoming_ids = [a.pk for a in upcoming]
        self.assertEqual(sorted(past_ids + upcoming_ids), sorted(a.pk for a in created))
        self.assertFalse(set(past_ids) & set(upcoming_ids))

    def test_split_never_includes_another_client(self):
        self._appt(at(-1, 9), client=self.other)
        self._appt(at(1, 9), client=self.other)
        mine_past = self._appt(at(-2, 9))
        mine_future = self._appt(at(2, 9))
        past, upcoming = past_and_upcoming(self.client, now=NOW)
        self.assertEqual(list(past), [mine_past])
        self.assertEqual(list(upcoming), [mine_future])

    def test_default_now_uses_current_time(self):
        # Appointments far in the past/future relative to real now.
        past_appt = self._appt(datetime.datetime(2000, 1, 1, 9, tzinfo=UTC))
        future_appt = self._appt(datetime.datetime(2100, 1, 1, 9, tzinfo=UTC))
        self.assertEqual(list(past_appointments(self.client)), [past_appt])
        self.assertEqual(list(upcoming_appointments(self.client)), [future_appt])
        self.assertEqual(
            list(client_appointments(self.client, upcoming_only=True)),
            [future_appt],
        )
