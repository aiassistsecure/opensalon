"""Tests for the bookings.breaks.update_break service.

Pins that a valid call updates only the given fields (None =
unchanged), that the end-after-start rule is checked against
the MERGED pair (moving only start past the stored end, or
only end to/before the stored start, is refused), that paid
toggles both ways, that staff_member is never changeable, and
that invalid shapes raise ValidationError writing nothing.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase

from bookings.breaks import update_break, validate_update_break
from bookings.models import Break
from saloncore.models import Salon
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
UTC = datetime.timezone.utc


def at(hour, minute=0):
    return datetime.datetime.combine(DAY, datetime.time(hour, minute),
                                     tzinfo=UTC)


class UpdateBreakServiceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.other = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.brk = Break.objects.create(
            staff_member=self.staff, start=at(12), end=at(12, 30),
            paid=False)

    def fresh(self):
        return Break.objects.get(pk=self.brk.pk)

    def test_updates_all_fields_and_keeps_staff(self):
        updated = update_break(
            self.brk, start=at(13), end=at(13, 45), paid=True)
        fresh = self.fresh()
        self.assertEqual(updated.pk, self.brk.pk)
        self.assertEqual(
            (fresh.start, fresh.end, fresh.paid, fresh.staff_member),
            (at(13), at(13, 45), True, self.staff))

    def test_partial_updates_leave_omitted_unchanged(self):
        update_break(self.brk, paid=True)
        fresh = self.fresh()
        self.assertEqual((fresh.start, fresh.end, fresh.paid),
                         (at(12), at(12, 30), True))
        update_break(self.brk, end=at(13))
        fresh = self.fresh()
        self.assertEqual((fresh.start, fresh.end, fresh.paid),
                         (at(12), at(13), True))
        update_break(self.brk, paid=False)
        self.assertFalse(self.fresh().paid)

    def test_validate_returns_merged_and_writes_nothing(self):
        result = validate_update_break(self.brk, end=at(13))
        self.assertEqual(result, (at(12), at(13), False))
        fresh = self.fresh()
        self.assertEqual((fresh.start, fresh.end), (at(12), at(12, 30)))
        with self.assertRaises(ValidationError):
            validate_update_break(self.brk, start=at(13))
        self.assertEqual(self.fresh().start, at(12))

    def test_merged_pair_rule_for_single_field_moves(self):
        for kwargs in ({"start": at(12, 30)}, {"start": at(13)},
                       {"end": at(12)}, {"end": at(11, 30)}):
            with self.assertRaises(ValidationError, msg=repr(kwargs)):
                update_break(self.brk, **kwargs)
        fresh = self.fresh()
        self.assertEqual((fresh.start, fresh.end), (at(12), at(12, 30)))
        # Moving both together to a valid new span works.
        update_break(self.brk, start=at(13), end=at(13, 15))
        self.assertEqual((self.fresh().start, self.fresh().end),
                         (at(13), at(13, 15)))

    def test_no_field_given_is_refused(self):
        with self.assertRaises(ValidationError):
            update_break(self.brk)
        with self.assertRaises(ValidationError):
            validate_update_break(self.brk)

    def test_naive_given_times_write_nothing(self):
        naive = datetime.datetime(2026, 11, 2, 13, 0)
        for kwargs in ({"start": naive}, {"end": naive}):
            with self.assertRaises(ValidationError):
                update_break(self.brk, **kwargs)
        self.assertEqual((self.fresh().start, self.fresh().end),
                         (at(12), at(12, 30)))

    def test_staff_member_is_not_changeable(self):
        with self.assertRaises(ValidationError):
            update_break(self.brk, staff_member=self.other, paid=True)
        fresh = self.fresh()
        self.assertEqual(fresh.staff_member, self.staff)
        self.assertFalse(fresh.paid)

    def test_aliases_accepted(self):
        update_break(self.brk, starts_at=at(12, 15), ends_at=at(12, 45))
        self.assertEqual((self.fresh().start, self.fresh().end),
                         (at(12, 15), at(12, 45)))

    def test_missing_or_unknown_break_writes_nothing(self):
        with self.assertRaises(ValidationError):
            update_break(None, paid=True)
        ghost = Break(pk=999999, staff_member=self.staff,
                      start=at(12), end=at(12, 30))
        with self.assertRaises(ValidationError):
            update_break(ghost, paid=True)
        unsaved = Break(staff_member=self.staff, start=at(12), end=at(1))
        with self.assertRaises(ValidationError):
            update_break(unsaved, paid=True)
        self.assertEqual(Break.objects.count(), 1)
        self.assertFalse(self.fresh().paid)
