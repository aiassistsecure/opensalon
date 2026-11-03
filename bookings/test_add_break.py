"""Tests for the bookings.breaks.add_break service.

Pins that a valid call creates exactly one Break mirroring the
model's fields (staff_member, start, end, paid), that paid and
unpaid both store verbatim, and that invalid shapes -- end at
or before start, missing/unknown staff, missing or naive
times -- raise ValidationError writing nothing. Fixtures are
tiny synthetic records -- unit logic only.
"""
import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase

from bookings.breaks import add_break, validate_add_break
from bookings.models import Break
from saloncore.models import Salon
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
UTC = datetime.timezone.utc


def at(hour, minute=0):
    return datetime.datetime.combine(DAY, datetime.time(hour, minute),
                                     tzinfo=UTC)


class AddBreakServiceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")

    def test_creates_paid_break_with_model_fields(self):
        created = add_break(self.staff, start=at(12), end=at(12, 30),
                            paid=True)
        self.assertEqual(Break.objects.count(), 1)
        self.assertEqual(created.staff_member, self.staff)
        self.assertEqual(created.start, at(12))
        self.assertEqual(created.end, at(12, 30))
        self.assertTrue(created.paid)

    def test_validate_add_break_writes_nothing(self):
        result = validate_add_break(
            self.staff, start=at(12), end=at(12, 30), paid=True)
        self.assertEqual(result, (at(12), at(12, 30), True))
        self.assertEqual(Break.objects.count(), 0)
        with self.assertRaises(ValidationError):
            validate_add_break(self.staff, start=at(12), end=at(12))
        self.assertEqual(Break.objects.count(), 0)

    def test_creates_unpaid_break_by_default(self):
        created = add_break(self.staff, at(13), at(14))
        self.assertEqual(Break.objects.count(), 1)
        self.assertFalse(created.paid)
        self.assertFalse(Break.objects.get().paid)

    def test_starts_at_ends_at_aliases(self):
        created = add_break(self.staff, starts_at=at(15), ends_at=at(15, 15),
                            paid=True)
        self.assertEqual(created.start, at(15))
        self.assertEqual(created.end, at(15, 15))

    def test_end_at_or_before_start_writes_nothing(self):
        for start, end in ((at(12), at(12)), (at(12), at(11, 30))):
            with self.assertRaises(ValidationError):
                add_break(self.staff, start=start, end=end, paid=True)
        self.assertEqual(Break.objects.count(), 0)

    def test_missing_staff_writes_nothing(self):
        with self.assertRaises(ValidationError):
            add_break(None, start=at(12), end=at(12, 30))
        unsaved = StaffMember(salon=self.salon, display_name="Ghost")
        with self.assertRaises(ValidationError):
            add_break(unsaved, start=at(12), end=at(12, 30))
        ghost = StaffMember(pk=999999, salon=self.salon,
                            display_name="Ghost")
        with self.assertRaises(ValidationError):
            add_break(ghost, start=at(12), end=at(12, 30))
        self.assertEqual(Break.objects.count(), 0)

    def test_missing_or_naive_times_write_nothing(self):
        naive = datetime.datetime(2026, 11, 2, 12, 0)
        for kwargs in ({"start": None, "end": at(12, 30)},
                       {"start": at(12), "end": None},
                       {"start": naive, "end": at(12, 30)},
                       {"start": at(12), "end": naive}):
            with self.assertRaises(ValidationError):
                add_break(self.staff, **kwargs)
        self.assertEqual(Break.objects.count(), 0)
