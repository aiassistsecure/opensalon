import datetime

from django.test import TestCase

from bookings.break_totals import break_totals, break_totals_report
from bookings.models import Break
from saloncore.models import Salon
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
NEXT = DAY + datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class BreakTotalsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")

    def _break(self, start, minutes, paid=False, staff=None):
        return Break.objects.create(
            staff_member=staff or self.staff, start=start,
            end=start + datetime.timedelta(minutes=minutes), paid=paid)

    def test_paid_unpaid_split_exact(self):
        self._break(at(DAY, 12), 30, paid=True)
        self._break(at(DAY, 15), 15, paid=True)
        self._break(at(DAY, 13), 60, paid=False)
        r = break_totals(self.salon, DAY)
        self.assertEqual(r.break_count, 3)
        self.assertEqual(r.total_break_minutes, 105)
        self.assertEqual((r.paid_break_count, r.paid_minutes), (2, 45))
        self.assertEqual((r.unpaid_break_count, r.unpaid_minutes), (1, 60))
        self.assertEqual(r.paid_minutes + r.unpaid_minutes, r.total_break_minutes)
        row = r.by_staff[0]
        self.assertEqual(row.staff_member_id, self.staff.pk)
        self.assertEqual(row.staff_name, "Stylist One")
        self.assertEqual((row.paid_minutes, row.unpaid_minutes), (45, 60))
        d = r.as_dict()
        self.assertEqual(d["total_break_minutes"], 105)
        self.assertEqual(d["by_staff"][0]["paid_minutes"], 45)

    def test_staff_scoping(self):
        self._break(at(DAY, 12), 30, paid=True)
        self._break(at(DAY, 12), 20, paid=False, staff=self.staff2)
        self._break(at(DAY, 13), 10, paid=True, staff=self.staff2)
        r = break_totals(self.salon, DAY)
        self.assertEqual([s.staff_name for s in r.by_staff],
                         ["Stylist One", "Stylist Two"])
        two = r.by_staff[1]
        self.assertEqual((two.break_count, two.total_break_minutes), (2, 30))
        self.assertEqual((two.paid_minutes, two.unpaid_minutes), (10, 20))
        only = break_totals(self.salon, DAY, staff_member=self.staff2)
        self.assertEqual(only.break_count, 2)
        self.assertEqual([s.staff_member_id for s in only.by_staff],
                         [self.staff2.pk])

    def test_date_range_filtering(self):
        self._break(at(DAY, 12), 30, paid=True)
        self._break(at(NEXT, 12), 45, paid=False)
        self._break(at(NEXT + datetime.timedelta(days=1), 12), 90, paid=True)
        single = break_totals_report(self.salon, DAY)
        self.assertEqual((single.break_count, single.total_break_minutes), (1, 30))
        rng = break_totals(self.salon, DAY, NEXT)
        self.assertEqual((rng.break_count, rng.total_break_minutes), (2, 75))
        self.assertEqual((rng.start_date, rng.end_date), (DAY, NEXT))

    def test_empty_range_is_zeros(self):
        r = break_totals(self.salon, DAY)
        self.assertEqual((r.break_count, r.total_break_minutes), (0, 0))
        self.assertEqual((r.paid_break_count, r.paid_minutes), (0, 0))
        self.assertEqual((r.unpaid_break_count, r.unpaid_minutes), (0, 0))
        self.assertEqual(r.by_staff, ())
        reversed_r = break_totals(self.salon, NEXT, DAY)
        self.assertEqual(reversed_r.break_count, 0)
        self.assertEqual(reversed_r.by_staff, ())

    def test_salon_isolation_via_staff(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        other_staff = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        self._break(at(DAY, 12), 30, paid=True)
        self._break(at(DAY, 12), 99, paid=True, staff=other_staff)
        r = break_totals(self.salon, DAY)
        self.assertEqual((r.break_count, r.total_break_minutes), (1, 30))
        self.assertEqual([s.staff_name for s in r.by_staff], ["Stylist One"])
        other_r = break_totals(other, DAY)
        self.assertEqual(other_r.total_break_minutes, 99)
