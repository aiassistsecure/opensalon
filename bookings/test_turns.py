import datetime

from django.test import TestCase

from bookings.models import TurnEntry
from bookings.turns import call_next, next_up, turns_taken_today, waiting_queue
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

UTC = datetime.timezone.utc
TODAY = datetime.date.today()
YESTERDAY = TODAY - datetime.timedelta(days=1)


class TurnEntryTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)

    def _entry(self, guest_name="Walk-in Guest", **kw):
        kw.setdefault("salon", self.salon)
        return TurnEntry.objects.create(guest_name=guest_name, **kw)

    def _age(self, entry, days):
        """Move an entry's arrival back ``days`` days."""
        when = datetime.datetime.combine(
            TODAY - datetime.timedelta(days=days),
            datetime.time(9, 0), tzinfo=UTC)
        TurnEntry.objects.filter(pk=entry.pk).update(created_at=when)
        entry.refresh_from_db()

    def test_creation_defaults(self):
        e = self._entry()
        self.assertEqual(e.status, TurnEntry.Status.WAITING)
        self.assertEqual(e.source, TurnEntry.Source.DESK)
        self.assertEqual(e.phone, "")
        self.assertIsNone(e.service)
        self.assertIsNone(e.requested_staff)
        self.assertIsNone(e.assigned_staff)
        self.assertIsNone(e.called_at)
        self.assertIsNone(e.seated_at)
        self.assertIsNotNone(e.created_at)
        self.assertIsNotNone(e.updated_at)

    def test_creation_with_all_fields(self):
        now = datetime.datetime.now(tz=UTC)
        e = self._entry(
            "Named Guest", phone="555-0100", service=self.service,
            requested_staff=self.staff, assigned_staff=self.staff2,
            status=TurnEntry.Status.IN_SERVICE,
            source=TurnEntry.Source.QR, called_at=now, seated_at=now)
        self.assertEqual(e.service, self.service)
        self.assertEqual(e.requested_staff, self.staff)
        self.assertEqual(e.assigned_staff, self.staff2)
        self.assertEqual(e.status, "in_service")
        self.assertEqual(e.source, "qr")

    def test_waiting_queue_arrival_order_waiting_only(self):
        first = self._entry("First")
        second = self._entry("Second")
        third = self._entry("Third")
        self._entry("Called", status=TurnEntry.Status.CALLED)
        self._entry("Gone", status=TurnEntry.Status.LEFT)
        other = Salon.objects.create(name="Other", timezone="UTC")
        self._entry("Elsewhere", salon=other)
        rows = list(waiting_queue(self.salon))
        self.assertEqual([e.pk for e in rows],
                         [first.pk, second.pk, third.pk])
        self.assertEqual(list(waiting_queue(None)), [])

    def test_turns_taken_today_counts_in_service_and_done(self):
        self._entry("A", assigned_staff=self.staff,
                    status=TurnEntry.Status.IN_SERVICE)
        self._entry("B", assigned_staff=self.staff,
                    status=TurnEntry.Status.DONE)
        self._entry("C", assigned_staff=self.staff,
                    status=TurnEntry.Status.WAITING)
        self._entry("D", assigned_staff=self.staff,
                    status=TurnEntry.Status.CALLED)
        self._entry("E", assigned_staff=self.staff,
                    status=TurnEntry.Status.LEFT)
        self.assertEqual(turns_taken_today(self.salon, self.staff, TODAY), 2)

    def test_turns_taken_today_only_that_member_and_day(self):
        self._entry("Mine", assigned_staff=self.staff,
                    status=TurnEntry.Status.DONE)
        self._entry("Theirs", assigned_staff=self.staff2,
                    status=TurnEntry.Status.DONE)
        self._entry("Unassigned", status=TurnEntry.Status.DONE)
        old = self._entry("Yesterday", assigned_staff=self.staff,
                          status=TurnEntry.Status.DONE)
        self._age(old, 1)
        other = Salon.objects.create(name="Other", timezone="UTC")
        self._entry("Elsewhere", salon=other, assigned_staff=self.staff,
                    status=TurnEntry.Status.DONE)
        self.assertEqual(turns_taken_today(self.salon, self.staff, TODAY), 1)
        self.assertEqual(turns_taken_today(self.salon, self.staff2, TODAY), 1)
        self.assertEqual(
            turns_taken_today(self.salon, self.staff, YESTERDAY), 1)
        self.assertEqual(turns_taken_today(None, self.staff, TODAY), 0)
        self.assertEqual(turns_taken_today(self.salon, None, TODAY), 0)


class TurnRotationTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        for member in (self.staff, self.staff2):
            RosterPattern.objects.create(
                staff_member=member, weekday=TODAY.weekday(),
                start_time=datetime.time(9, 0), end_time=datetime.time(17, 0))

    def _entry(self, guest_name="Walk-in Guest", **kw):
        kw.setdefault("salon", self.salon)
        return TurnEntry.objects.create(guest_name=guest_name, **kw)

    def test_next_up_picks_a_working_member(self):
        self.assertIn(next_up(self.salon, TODAY), (self.staff, self.staff2))

    def test_next_up_skips_member_not_working_that_day(self):
        RosterPattern.objects.filter(staff_member=self.staff2).delete()
        self.assertEqual(next_up(self.salon, TODAY), self.staff)

    def test_rotation_alternates_on_turns_taken(self):
        first = next_up(self.salon, TODAY)
        other = self.staff2 if first == self.staff else self.staff
        self._entry("Served", assigned_staff=first,
                    status=TurnEntry.Status.DONE)
        self.assertEqual(next_up(self.salon, TODAY), other)

    def test_capability_filter_excludes_member_without_the_service(self):
        from team.models import StaffService
        StaffService.objects.create(
            staff_member=self.staff2, service=self.service, enabled=True)
        self.assertEqual(
            next_up(self.salon, TODAY, service=self.service), self.staff2)

    def test_call_next_assigns_rotation_not_the_request(self):
        self._entry("Served", assigned_staff=self.staff,
                    status=TurnEntry.Status.DONE)
        entry = self._entry("Waiting", requested_staff=self.staff)
        called = call_next(self.salon, TODAY)
        self.assertEqual(called.pk, entry.pk)
        self.assertEqual(called.assigned_staff, self.staff2)
        self.assertEqual(called.status, TurnEntry.Status.CALLED)
        self.assertIsNotNone(called.called_at)

    def test_call_next_empty_queue_and_nobody_working(self):
        self.assertIsNone(call_next(self.salon, TODAY))
        self._entry("Waiting")
        RosterPattern.objects.all().delete()
        self.assertIsNone(call_next(self.salon, TODAY))
