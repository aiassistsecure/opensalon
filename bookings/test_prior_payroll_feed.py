import csv, datetime, io  # noqa: E401
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Break
from bookings.payroll_feed import payroll_feed
from bookings.prior_payroll_feed import prior_payroll_feed_report
from bookings.prior_payroll_feed_export import ( PRIOR_PAYROLL_FEED_EXPORT_FIELDNAMES, export_prior_payroll_feed_csv, prior_payroll_feed_rows)
from saloncore.models import Salon
from team.models import AttendanceRecord, RosterPattern, StaffMember

DAY = datetime.date(2026, 11, 2)  # Monday, current window
PRIOR_DAY = DAY - datetime.timedelta(days=1)  # Sunday
NEXT = DAY + datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class PriorPayrollFeedTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(salon=self.salon, display_name="Stylist Two")
        for staff, wd, span in ((self.staff, 0, (9, 17)), (self.staff, 6, (9, 13)), (self.staff2, 0, (10, 14))):
            RosterPattern.objects.create(staff_member=staff, weekday=wd, start_time=datetime.time(span[0]), end_time=datetime.time(span[1]))

    def _session(self, staff, day, start, end):
        AttendanceRecord.objects.create(staff_member=staff, event_type="check_in", recorded_at=at(day, *start))
        if end is not None:
            AttendanceRecord.objects.create(staff_member=staff, event_type="check_out", recorded_at=at(day, *end))

    def _break(self, staff, day, hour, minutes, paid):
        start = at(day, hour)
        Break.objects.create(staff_member=staff, start=start, end=start + datetime.timedelta(minutes=minutes), paid=paid)

    def _book(self):
        # Prior (Sun): One rostered 240, session 240 closed, paid break 30.
        self._session(self.staff, PRIOR_DAY, (9, 0), (13, 0))
        self._break(self.staff, PRIOR_DAY, 12, 30, paid=True)
        # Current (Mon): One rostered 480, session 510, breaks 45p+15u;
        # Two rostered 240, open session, unpaid break 20.
        self._session(self.staff, DAY, (9, 0), (17, 30))
        self._session(self.staff2, DAY, (10, 0), None)
        self._break(self.staff, DAY, 12, 45, paid=True)
        self._break(self.staff, DAY, 13, 15, paid=False)
        self._break(self.staff2, DAY, 12, 20, paid=False)

    def test_windows_verbatim_and_totals(self):
        self._book()
        r = prior_payroll_feed_report(self.salon, DAY, DAY)
        self.assertEqual((r.start_date, r.end_date), (DAY, DAY))
        self.assertEqual((r.prior_start_date, r.prior_end_date), (PRIOR_DAY, PRIOR_DAY))
        self.assertEqual(r.days, 1)
        self.assertEqual(r.current, payroll_feed(self.salon, DAY, DAY))
        self.assertEqual(r.prior, payroll_feed(self.salon, PRIOR_DAY, PRIOR_DAY))
        self.assertEqual((r.rostered_minutes.current, r.rostered_minutes.prior, r.rostered_minutes.delta, r.rostered_minutes.percent_change), (720, 240, 480, Decimal("200.00")))
        self.assertEqual((r.actual_minutes.current, r.actual_minutes.prior, r.actual_minutes.delta), (510, 240, 270))
        self.assertEqual((r.paid_minutes.current, r.paid_minutes.prior, r.paid_minutes.delta, r.paid_minutes.percent_change), (45, 30, 15, Decimal("50.00")))
        self.assertEqual((r.unpaid_minutes.current, r.unpaid_minutes.prior), (35, 0))
        self.assertIsNone(r.unpaid_minutes.percent_change)
        self.assertEqual(r.as_dict()["rostered_minutes"]["delta"], 480)
        self.assertEqual(r.as_dict()["by_staff"][0]["staff_name"], "Stylist One")

    def test_per_staff_keying_scoping_and_prior_zero(self):
        self._book()
        r = prior_payroll_feed_report(self.salon, DAY, DAY)
        self.assertEqual([s.staff_name for s in r.by_staff], ["Stylist One", "Stylist Two"])
        one, two = r.by_staff
        self.assertEqual(one.staff_member_id, self.staff.pk)
        self.assertEqual((one.rostered_minutes.current, one.rostered_minutes.prior), (480, 240))
        self.assertEqual((one.attendance_sessions.current, one.closed_sessions.current), (1, 1))
        self.assertEqual((two.rostered_minutes.current, two.rostered_minutes.prior), (240, 0))
        self.assertIsNone(two.rostered_minutes.percent_change)  # zero prior
        self.assertIsNone(two.open_sessions.percent_change)
        self.assertEqual((two.current.open_sessions, two.prior.open_sessions), (1, 0))
        scoped = prior_payroll_feed_report(self.salon, DAY, DAY, staff_member=self.staff2)
        self.assertEqual([s.staff_member_id for s in scoped.by_staff], [self.staff2.pk])
        self.assertEqual(scoped.rostered_minutes.current, 240)

    def test_equal_length_aliases_empty_and_reversed(self):
        self._book()
        start = DAY - datetime.timedelta(days=6)
        r = prior_payroll_feed_report(self.salon, start_date=start, end_date=DAY)
        self.assertEqual(r.days, 7)
        self.assertEqual((r.prior_start_date, r.prior_end_date), (start - datetime.timedelta(days=7), start - datetime.timedelta(days=1)))
        other = Salon.objects.create(name="Other", timezone="UTC")
        empty = prior_payroll_feed_report(other, DAY, DAY)
        self.assertEqual((empty.rostered_minutes.current, empty.rostered_minutes.prior, empty.rostered_minutes.delta), (0, 0, 0))
        self.assertIsNone(empty.rostered_minutes.percent_change)
        self.assertEqual(empty.by_staff, ())
        with self.assertRaises(ValueError):
            prior_payroll_feed_report(self.salon, NEXT, DAY)
        with self.assertRaises(ValueError):
            export_prior_payroll_feed_csv(self.salon, NEXT, DAY)
        with self.assertRaises(ValueError):
            prior_payroll_feed_report(self.salon)

    def test_salon_isolation(self):
        self._book()
        other = Salon.objects.create(name="Other", timezone="UTC")
        outsider = StaffMember.objects.create(salon=other, display_name="Outsider")
        RosterPattern.objects.create(staff_member=outsider, weekday=0, start_time=datetime.time(9), end_time=datetime.time(17))
        self._break(outsider, DAY, 12, 99, paid=True)
        r = prior_payroll_feed_report(self.salon, DAY, DAY)
        self.assertNotIn(outsider.pk, [s.staff_member_id for s in r.by_staff])
        self.assertEqual(r.total_break_minutes.current, 80)

    def test_export_agreement(self):
        self._book()
        rows = prior_payroll_feed_rows(self.salon, DAY, DAY)
        self.assertEqual(len(rows), 3)  # total + 2 staff
        self.assertEqual((rows[0]["staff_member_id"], rows[0]["staff_name"]), ("", ""))
        self.assertEqual((rows[0]["current_rostered_minutes"], rows[0]["prior_rostered_minutes"], rows[0]["rostered_minutes_delta"], rows[0]["rostered_minutes_percent_change"]), (720, 240, 480, Decimal("200.00")))
        self.assertEqual(rows[0]["prior_end_date"], PRIOR_DAY.isoformat())
        text = export_prior_payroll_feed_csv(self.salon, DAY, DAY)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0], PRIOR_PAYROLL_FEED_EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(parsed), len(rows))
        for raw, flat in zip(parsed, rows):
            for key, value in flat.items():
                expected = ("" if value is None else f"{value:.2f}" if key.endswith("percent_change") else str(value))
                self.assertEqual(raw[key], expected, key)
        two = [x for x in parsed if x["staff_name"] == "Stylist Two"][0]
        self.assertEqual(two["rostered_minutes_percent_change"], "")

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_payroll_feed", salon_id=self.salon.pk, start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), export_prior_payroll_feed_csv(self.salon, DAY, DAY))
        for kwargs in (dict(salon_id=self.salon.pk + 1000, start_date=DAY, end_date=DAY), dict(salon_id=self.salon.pk, start_date=NEXT, end_date=DAY), dict(salon_id=self.salon.pk, start_date="not-a-date", end_date=DAY), dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_prior_payroll_feed", stdout=io.StringIO(), **kwargs)
        m = mock.mock_open()
        with mock.patch("bookings.management.commands.export_prior_payroll_feed.open", m):
            call_command("export_prior_payroll_feed", salon_id=self.salon.pk, start_date="2026-11-02", end_date="2026-11-02", output="out.csv")
        m().write.assert_called_once_with( export_prior_payroll_feed_csv(self.salon, DAY, DAY))
