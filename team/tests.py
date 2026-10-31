import datetime

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from saloncore.models import Salon, StaffLevel
from team.models import AttendanceRecord, RosterPattern, StaffMember


class StaffMemberModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint On The Avenue")
        self.level = StaffLevel.objects.create(name="Level 6", salon=self.salon)

    def test_creation_and_salon_fk(self):
        member = StaffMember.objects.create(
            display_name="Maribel Gonzalez", salon=self.salon
        )
        self.assertEqual(member.salon, self.salon)
        self.assertIn(member, list(self.salon.staff_members.all()))
        self.assertTrue(member.active)

    def test_str_returns_display_name(self):
        member = StaffMember(display_name="Sonia Taylor", salon=self.salon)
        self.assertEqual(str(member), "Sonia Taylor")

    def test_level_link(self):
        member = StaffMember.objects.create(
            display_name="Eva Bonilla", salon=self.salon, staff_level=self.level
        )
        self.assertEqual(member.staff_level, self.level)
        self.assertIn(member, list(self.level.members.all()))

    def test_level_is_optional(self):
        member = StaffMember.objects.create(
            display_name="No Level", salon=self.salon
        )
        self.assertIsNone(member.staff_level)

    def test_level_delete_sets_null(self):
        member = StaffMember.objects.create(
            display_name="Dawn Davalos", salon=self.salon, staff_level=self.level
        )
        self.level.delete()
        member.refresh_from_db()
        self.assertIsNone(member.staff_level)

    def test_online_bookable_defaults_true(self):
        member = StaffMember.objects.create(
            display_name="Default Bookable", salon=self.salon
        )
        member.refresh_from_db()
        self.assertTrue(member.online_bookable)

    def test_online_bookable_false_case(self):
        member = StaffMember.objects.create(
            display_name="Not Bookable", salon=self.salon, online_bookable=False
        )
        member.refresh_from_db()
        self.assertFalse(member.online_bookable)

    def test_ordering_by_display_name(self):
        StaffMember.objects.create(display_name="Zoe", salon=self.salon)
        StaffMember.objects.create(display_name="Amy", salon=self.salon)
        names = list(StaffMember.objects.values_list("display_name", flat=True))
        self.assertEqual(names, ["Amy", "Zoe"])


class RosterPatternModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint On The Avenue")
        self.member = StaffMember.objects.create(
            display_name="Maribel Gonzalez", salon=self.salon
        )

    def _create(self, **kwargs):
        defaults = dict(
            staff_member=self.member,
            weekday=RosterPattern.Weekday.MONDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
        defaults.update(kwargs)
        return RosterPattern.objects.create(**defaults)

    def test_creation(self):
        pattern = self._create()
        self.assertEqual(pattern.staff_member, self.member)
        self.assertEqual(pattern.weekday, 0)
        self.assertEqual(pattern.start_time, datetime.time(9, 0))
        self.assertEqual(pattern.end_time, datetime.time(17, 0))
        self.assertTrue(pattern.active)

    def test_weekday_choices(self):
        self.assertEqual(
            list(RosterPattern.Weekday.choices),
            [(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"),
             (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday")],
        )
        pattern = self._create(weekday=RosterPattern.Weekday.SUNDAY)
        self.assertEqual(pattern.get_weekday_display(), "Sunday")

    def test_invalid_end_equal_start_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._create(end_time=datetime.time(9, 0))

    def test_invalid_end_before_start_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._create(end_time=datetime.time(8, 0))

    def test_per_staff_related_name(self):
        other = StaffMember.objects.create(display_name="Sonia Taylor", salon=self.salon)
        mine = self._create()
        self._create(staff_member=other, weekday=1)
        self.assertEqual(list(self.member.roster_patterns.all()), [mine])
        self.assertEqual(other.roster_patterns.count(), 1)

    def test_inactive_pattern_retained(self):
        pattern = self._create(active=False)
        pattern.refresh_from_db()
        self.assertFalse(pattern.active)
        self.assertIn(pattern, list(RosterPattern.objects.all()))
        self.assertIn(pattern, list(self.member.roster_patterns.all()))

    def test_ordering_by_weekday_then_start(self):
        self._create(weekday=2, start_time=datetime.time(10, 0), end_time=datetime.time(12, 0))
        self._create(weekday=0, start_time=datetime.time(13, 0), end_time=datetime.time(17, 0))
        self._create(weekday=0, start_time=datetime.time(9, 0), end_time=datetime.time(12, 0))
        rows = list(RosterPattern.objects.values_list("weekday", "start_time"))
        self.assertEqual(rows, [(0, datetime.time(9, 0)), (0, datetime.time(13, 0)), (2, datetime.time(10, 0))])


class AttendanceRecordModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint On The Avenue")
        self.member = StaffMember.objects.create(
            display_name="Maribel Gonzalez", salon=self.salon
        )
        self.base = timezone.now() - datetime.timedelta(hours=4)

    def _record(self, event_type, hours=0, **kwargs):
        return AttendanceRecord.objects.create(
            staff_member=self.member,
            event_type=event_type,
            recorded_at=self.base + datetime.timedelta(hours=hours),
            **kwargs,
        )

    def test_event_records_against_staff_member(self):
        rec = self._record(AttendanceRecord.EventType.CHECK_IN)
        self.assertEqual(rec.staff_member, self.member)
        self.assertEqual(list(self.member.attendance_records.all()), [rec])

    def test_recorded_at_defaults_to_now(self):
        before = timezone.now()
        rec = AttendanceRecord.objects.create(
            staff_member=self.member,
            event_type=AttendanceRecord.EventType.CHECK_IN,
        )
        self.assertGreaterEqual(rec.recorded_at, before)
        self.assertLessEqual(rec.recorded_at, timezone.now())

    def test_note_optional(self):
        self.assertEqual(self._record(AttendanceRecord.EventType.CHECK_IN).note, "")
        noted = self._record(
            AttendanceRecord.EventType.CHECK_OUT, hours=1, note="Left early"
        )
        self.assertEqual(noted.note, "Left early")

    def test_ordering_latest_first(self):
        self._record(AttendanceRecord.EventType.CHECK_IN, hours=0)
        self._record(AttendanceRecord.EventType.CHECK_OUT, hours=2)
        self._record(AttendanceRecord.EventType.CHECK_IN, hours=1)
        times = list(
            self.member.attendance_records.values_list("recorded_at", flat=True)
        )
        self.assertEqual(times, sorted(times, reverse=True))

    def test_not_checked_in_with_no_events(self):
        self.assertFalse(self.member.is_checked_in())

    def test_checked_in_after_check_in(self):
        self._record(AttendanceRecord.EventType.CHECK_IN)
        self.assertTrue(self.member.is_checked_in())

    def test_not_checked_in_after_check_out(self):
        self._record(AttendanceRecord.EventType.CHECK_IN, hours=0)
        self._record(AttendanceRecord.EventType.CHECK_OUT, hours=1)
        self.assertFalse(self.member.is_checked_in())

    def test_checked_in_again_after_second_check_in(self):
        self._record(AttendanceRecord.EventType.CHECK_IN, hours=0)
        self._record(AttendanceRecord.EventType.CHECK_OUT, hours=1)
        self._record(AttendanceRecord.EventType.CHECK_IN, hours=2)
        self.assertTrue(self.member.is_checked_in())

    def test_is_checked_in_is_per_member(self):
        other = StaffMember.objects.create(display_name="Sonia Taylor", salon=self.salon)
        self._record(AttendanceRecord.EventType.CHECK_IN)
        self.assertTrue(self.member.is_checked_in())
        self.assertFalse(other.is_checked_in())


class StrictConstraintsTests(TestCase):
    """N-M17: StrictConstraints enforces team Meta.constraints on save().

    NEDB DYOR §9.3/§9.4: schemaless NEDB creates no DB constraints, so
    the declared catalog is enforced in the app layer; violations
    surface as IntegrityError, as on an enforcing backend.
    """

    def setUp(self):
        self.salon = Salon.objects.create(name="Mint On The Avenue")
        self.other_salon = Salon.objects.create(name="Other Salon")
        self.member = StaffMember.objects.create(
            display_name="Maribel Gonzalez", salon=self.salon, external_id="staff-1"
        )

    def test_duplicate_staff_external_id_per_salon_rejected(self):
        duplicate = StaffMember(
            display_name="Copy", salon=self.salon, external_id="staff-1"
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                duplicate.save()
        self.assertEqual(StaffMember.objects.filter(external_id="staff-1").count(), 1)

    def test_same_external_id_in_other_salon_allowed(self):
        StaffMember.objects.create(
            display_name="Other", salon=self.other_salon, external_id="staff-1"
        )

    def test_duplicate_blank_staff_external_id_allowed(self):
        StaffMember.objects.create(display_name="A", salon=self.salon)
        StaffMember.objects.create(display_name="B", salon=self.salon)

    def test_update_into_duplicate_staff_external_id_rejected(self):
        other = StaffMember.objects.create(
            display_name="Sonia Taylor", salon=self.salon, external_id="staff-2"
        )
        other.external_id = "staff-1"
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                other.save()

    def test_roster_end_not_after_start_rejected_on_save(self):
        pattern = RosterPattern(
            staff_member=self.member, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(9, 0),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                pattern.save()
        self.assertEqual(RosterPattern.objects.count(), 0)

    def test_roster_update_into_invalid_range_rejected(self):
        pattern = RosterPattern.objects.create(
            staff_member=self.member, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0),
        )
        pattern.end_time = datetime.time(8, 0)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                pattern.save()

    def test_legitimate_saves_and_updates_pass(self):
        self.member.display_name = "Maribel G."
        self.member.save()
        self.member.save(update_fields=["display_name"])
        pattern = RosterPattern.objects.create(
            staff_member=self.member, weekday=1,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0),
        )
        pattern.end_time = datetime.time(18, 0)
        pattern.save()
        pattern.refresh_from_db()
        self.assertEqual(pattern.end_time, datetime.time(18, 0))
