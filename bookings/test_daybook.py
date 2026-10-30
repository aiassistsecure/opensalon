import datetime

from django.test import TestCase

from bookings.daybook import blocks_for_day, breaks_for_day, daybook_context
from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class DaybookTestCase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )

    def _roster(self, staff=None, weekday=0, start=(9, 0), end=(17, 0), **kw):
        return RosterPattern.objects.create(
            staff_member=staff or self.staff, weekday=weekday,
            start_time=datetime.time(*start), end_time=datetime.time(*end), **kw,
        )

    def _appt(self, start_h, end_h, staff=None, day=MONDAY, **kw):
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.staff,
            service=self.service, start=at(day, start_h), end=at(day, end_h), **kw,
        )


class BlocksForDayTests(DaybookTestCase):
    def test_block_carries_contract_fields(self):
        appt = self._appt(11, 12, status=Appointment.Status.CONFIRMED)
        (column,) = blocks_for_day(self.salon, MONDAY)
        self.assertEqual(column.staff_member, self.staff)
        self.assertEqual(column.staff_member_id, self.staff.pk)
        self.assertEqual(column.display_name, "Stylist One")
        self.assertTrue(column.online_bookable)
        (block,) = column.blocks
        self.assertEqual(block.appointment_id, appt.pk)
        self.assertEqual(block.staff_member_id, self.staff.pk)
        self.assertEqual(block.client_display_name, "Test Example")
        self.assertEqual(block.service_name, "Haircut")
        self.assertEqual(block.service_category_name, "Hair")
        self.assertEqual((block.start, block.end), (at(MONDAY, 11), at(MONDAY, 12)))
        self.assertEqual(block.status, "confirmed")

    def test_columns_per_staff_ordered_and_blocks_by_start(self):
        other = StaffMember.objects.create(
            salon=self.salon, display_name="Another Stylist"
        )
        self._appt(14, 15)
        self._appt(9, 10)
        self._appt(11, 12, staff=other)
        columns = blocks_for_day(self.salon, MONDAY)
        self.assertEqual([c.staff_member for c in columns], [other, self.staff])
        self.assertEqual(
            [b.start for b in columns[1].blocks], [at(MONDAY, 9), at(MONDAY, 14)]
        )
        self.assertEqual(len(columns[0].blocks), 1)

    def test_active_staff_without_appointments_gets_empty_column(self):
        StaffMember.objects.create(salon=self.salon, display_name="Idle")
        columns = blocks_for_day(self.salon, MONDAY)
        self.assertEqual([len(c.blocks) for c in columns], [0, 0])

    def test_cancelled_excluded_other_statuses_kept(self):
        self._appt(9, 10, status=Appointment.Status.CANCELLED)
        self._appt(11, 12, status=Appointment.Status.NO_SHOW)
        (column,) = blocks_for_day(self.salon, MONDAY)
        self.assertEqual([b.status for b in column.blocks], ["no_show"])

    def test_inactive_other_salon_and_other_day_excluded(self):
        inactive = StaffMember.objects.create(
            salon=self.salon, display_name="Inactive", active=False
        )
        other_salon = Salon.objects.create(name="Other")
        outsider = StaffMember.objects.create(salon=other_salon, display_name="Out")
        self._appt(9, 10, staff=inactive)
        self._appt(9, 10, staff=outsider)
        self._appt(9, 10, day=MONDAY + datetime.timedelta(days=1))
        self._appt(9, 10)
        columns = blocks_for_day(self.salon, MONDAY)
        self.assertEqual([c.staff_member for c in columns], [self.staff])
        self.assertEqual(len(columns[0].blocks), 1)

    def test_datetime_day_reduced_to_date(self):
        self._appt(9, 10)
        columns = blocks_for_day(self.salon, at(MONDAY, 23))
        self.assertEqual(len(columns[0].blocks), 1)


class BreaksForDayTests(DaybookTestCase):
    def _gaps(self, result, staff=None):
        entry = next(r for r in result if r.staff_member == (staff or self.staff))
        return [(i.start, i.end) for i in entry.intervals]

    def test_appointment_inside_roster_is_a_gap(self):
        self._roster()
        self._appt(11, 12)
        self.assertEqual(
            self._gaps(breaks_for_day(self.salon, MONDAY)),
            [(at(MONDAY, 11), at(MONDAY, 12))],
        )

    def test_gap_between_roster_windows_is_a_break(self):
        self._roster(end=(12, 0))
        self._roster(start=(13, 0))
        self.assertEqual(
            self._gaps(breaks_for_day(self.salon, MONDAY)),
            [(at(MONDAY, 12), at(MONDAY, 13))],
        )

    def test_uninterrupted_roster_has_no_breaks(self):
        self._roster()
        self.assertEqual(self._gaps(breaks_for_day(self.salon, MONDAY)), [])

    def test_no_roster_that_weekday_means_no_entry(self):
        self._roster(weekday=1)
        self.assertEqual(breaks_for_day(self.salon, MONDAY), [])


class DaybookContextTests(DaybookTestCase):
    def test_context_shape_merges_blocks_and_breaks(self):
        self._roster()
        self._appt(11, 12)
        context = daybook_context(self.salon, MONDAY)
        self.assertEqual(context["salon"], self.salon)
        self.assertEqual(context["day"], MONDAY)
        (column,) = context["columns"]
        self.assertEqual(column["staff_member_id"], self.staff.pk)
        self.assertEqual(column["display_name"], "Stylist One")
        self.assertEqual(len(column["blocks"]), 1)
        self.assertEqual(
            [(b.start, b.end) for b in column["breaks"]],
            [(at(MONDAY, 11), at(MONDAY, 12))],
        )

    def test_context_column_without_roster_has_empty_breaks(self):
        context = daybook_context(self.salon, MONDAY)
        self.assertEqual(context["columns"][0]["breaks"], [])
