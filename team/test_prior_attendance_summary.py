"""Tests for prior-period attendance summary: service, export, command."""
import csv
import datetime
import io
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from unittest import mock

from saloncore.models import Salon
from team.attendance_summary import (AttendanceSummary, DayAttendanceSummary,
                                     attendance_summary)
from team.models import AttendanceRecord, StaffMember
from team.prior_attendance_summary import prior_attendance_summary_report
from team.prior_attendance_summary_export import (
    PRIOR_ATTENDANCE_SUMMARY_EXPORT_FIELDNAMES,
    export_prior_attendance_summary, export_prior_attendance_summary_csv)

DAY = datetime.date(2026, 11, 2)
PRIOR_DAY = datetime.date(2026, 11, 1)
NEXT = datetime.date(2026, 11, 3)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class PriorAttendanceSummaryTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(salon=self.salon, display_name="Stylist One")
        self.other = StaffMember.objects.create(salon=self.salon, display_name="Stylist Two")
        self.late_joiner = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Three", active=False)

    def _session(self, staff, day, start=(9, 0), end=(17, 0)):
        AttendanceRecord.objects.create(staff_member=staff, event_type="check_in",
                                        recorded_at=at(day, *start))
        if end is not None:
            AttendanceRecord.objects.create(staff_member=staff, event_type="check_out",
                                            recorded_at=at(day, *end))

    def _book(self):
        self._session(self.staff, PRIOR_DAY)                 # prior: 480, closed
        self._session(self.other, PRIOR_DAY, end=(13, 0))    # prior: 240, closed
        self._session(self.staff, DAY, end=(13, 0))          # current: 240, closed
        self._session(self.other, DAY, end=None)             # current: open, 0
        self._session(self.late_joiner, DAY)                 # current only: 480

    def test_both_windows_verbatim_and_totals(self):
        self._book()
        r = prior_attendance_summary_report(self.salon, DAY, DAY)
        self.assertEqual((r.start_date, r.prior_start_date, r.prior_end_date),
                         (DAY, PRIOR_DAY, PRIOR_DAY))
        self.assertEqual(r.days, 1)
        self.assertEqual(r.current.sessions_count, attendance_summary(self.salon, DAY, DAY).sessions_count)
        self.assertEqual(r.prior.total_minutes, attendance_summary(self.salon, PRIOR_DAY, PRIOR_DAY).total_minutes)
        self.assertEqual((r.sessions_count.current, r.sessions_count.prior,
                          r.sessions_count.delta, r.sessions_count.percent_change),
                         (3, 2, 1, Decimal("50.00")))
        self.assertEqual((r.closed_sessions.current, r.closed_sessions.prior,
                          r.closed_sessions.delta, r.closed_sessions.percent_change),
                         (2, 2, 0, Decimal("0.00")))
        self.assertEqual((r.open_sessions.current, r.open_sessions.prior,
                          r.open_sessions.delta), (1, 0, 1))
        self.assertIsNone(r.open_sessions.percent_change)
        self.assertEqual((r.total_minutes.current, r.total_minutes.prior,
                          r.total_minutes.delta, r.total_minutes.percent_change),
                         (720, 720, 0, Decimal("0.00")))
        self.assertEqual(r.as_dict()["sessions_count"]["delta"], 1)
        # per_day verbatim vs source, both windows (single-day here).
        cur_day = attendance_summary(self.salon, DAY, DAY).per_day[0]
        pri_day = attendance_summary(self.salon, PRIOR_DAY, PRIOR_DAY).per_day[0]
        self.assertEqual(len(r.per_day), 1)
        entry = r.per_day[0]
        self.assertEqual((entry.day, entry.prior_day, entry.offset), (DAY, PRIOR_DAY, 0))
        self.assertIs(r.by_day, r.per_day)
        self.assertIs(r.for_day(DAY), entry)
        for m in ("sessions_count", "closed_sessions", "open_sessions",
                  "total_minutes", "staff_count"):
            d = getattr(entry, m)
            self.assertEqual((d.current, d.prior), (getattr(cur_day, m), getattr(pri_day, m)))
            self.assertEqual(d.delta, d.current - d.prior)
        self.assertEqual((entry.current, entry.prior), (cur_day, pri_day))
        self.assertEqual(r.as_dict()["per_day"][0]["sessions_count"]["current"], 3)
        self.assertEqual(r.as_dict()["by_day"], r.as_dict()["per_day"])

    def test_per_staff_deltas_and_union(self):
        self._book()
        r = prior_attendance_summary_report(self.salon, DAY, DAY)
        self.assertEqual([s.staff_name for s in r.by_staff],
                         ["Stylist One", "Stylist Three", "Stylist Two"])
        one = r.for_staff(self.staff)
        self.assertEqual((one.total_minutes.current, one.total_minutes.prior,
                          one.total_minutes.delta, one.total_minutes.percent_change),
                         (240, 480, -240, Decimal("-50.00")))
        two = r.for_staff(self.other)
        self.assertEqual((two.open_sessions.current, two.closed_sessions.delta), (1, -1))
        three = r.for_staff(self.late_joiner)
        self.assertEqual((three.sessions_count.current, three.sessions_count.prior,
                          three.total_minutes.current), (1, 0, 480))
        self.assertIsNone(three.sessions_count.percent_change)

    def test_per_day_offset_alignment_multi_day(self):
        # Current window Nov 2-4, prior Oct 30-Nov 1; distinct
        # minutes per offset so date-keyed pairing would fail.
        d = datetime.timedelta(days=1)
        self._session(self.staff, DAY - 3 * d, end=(10, 0))       # prior off0: 60
        self._session(self.staff, DAY - 1 * d, end=(12, 0))       # prior off2: 180
        self._session(self.staff, DAY, end=(11, 0))               # cur off0: 120
        self._session(self.other, DAY + 1 * d, end=None)          # cur off1: open
        self._session(self.staff, DAY + 2 * d, end=(10, 30))      # cur off2: 90
        r = prior_attendance_summary_report(self.salon, DAY, DAY + 2 * d)
        self.assertEqual([(e.day, e.prior_day, e.offset) for e in r.per_day],
                         [(DAY, DAY - 3 * d, 0), (DAY + d, DAY - 2 * d, 1),
                          (DAY + 2 * d, DAY - d, 2)])
        self.assertEqual([(e.total_minutes.current, e.total_minutes.prior,
                           e.total_minutes.delta) for e in r.per_day],
                         [(120, 60, 60), (0, 0, 0), (90, 180, -90)])
        self.assertEqual([(e.sessions_count.current, e.sessions_count.prior)
                          for e in r.per_day], [(1, 1), (1, 0), (1, 1)])
        self.assertEqual((r.per_day[1].open_sessions.current,
                          r.per_day[1].staff_count.current), (1, 1))
        cur = attendance_summary(self.salon, DAY, DAY + 2 * d)
        pri = attendance_summary(self.salon, DAY - 3 * d, DAY - d)
        for i, e in enumerate(r.per_day):
            self.assertEqual((e.current, e.prior), (cur.per_day[i], pri.per_day[i]))

    def test_per_day_unequal_length_zero_filled(self):
        def fake(salon, first, last):
            days = {DAY: [DayAttendanceSummary(
                        day=DAY, sessions_count=2, closed_sessions=2,
                        total_duration=datetime.timedelta(minutes=90)),
                        DayAttendanceSummary(day=NEXT, sessions_count=1),
                        DayAttendanceSummary(
                            day=NEXT + datetime.timedelta(days=1),
                            sessions_count=4)],
                    PRIOR_DAY - datetime.timedelta(days=1): [
                        DayAttendanceSummary(
                            day=PRIOR_DAY - datetime.timedelta(days=1),
                            sessions_count=1)]}
            per_day = days[first]
            return AttendanceSummary(salon=salon, start_date=first,
                                     end_date=last, per_staff=[], per_day=per_day)
        with mock.patch("team.prior_attendance_summary.attendance_summary",
                        side_effect=fake):
            r = prior_attendance_summary_report(self.salon, DAY, NEXT)
        # Current has 3 entries, prior 1: offsets 1-2 prior zero-filled,
        # dated prior_start+offset; no entry is dropped.
        self.assertEqual(len(r.per_day), 3)
        self.assertEqual([(e.sessions_count.current, e.sessions_count.prior,
                           e.sessions_count.delta) for e in r.per_day],
                         [(2, 1, 1), (1, 0, 1), (4, 0, 4)])
        self.assertEqual(r.per_day[1].prior_day,
                         PRIOR_DAY)  # prior window start + 1 day
        self.assertEqual(r.per_day[0].total_minutes.prior, 0)

    def test_zero_prior_and_empty(self):
        other = Salon.objects.create(name="Other", timezone="UTC")
        r = prior_attendance_summary_report(other, DAY, DAY)
        self.assertEqual(r.by_staff, ())
        self.assertEqual((r.sessions_count.current, r.sessions_count.delta), (0, 0))
        self.assertIsNone(r.sessions_count.percent_change)

    def test_equal_length_aliases_and_errors(self):
        self._book()
        start = DAY - datetime.timedelta(days=6)
        r = prior_attendance_summary_report(self.salon, start_date=start, end_date=DAY)
        self.assertEqual((r.days, r.prior_start_date, r.prior_end_date),
                         (7, start - datetime.timedelta(days=7), start - datetime.timedelta(days=1)))
        self.assertEqual(prior_attendance_summary_report(self.salon, DAY).sessions_count.current, 3)
        for call in (lambda: prior_attendance_summary_report(self.salon, NEXT, DAY),
                     lambda: prior_attendance_summary_report(None, DAY, DAY),
                     lambda: prior_attendance_summary_report(self.salon),
                     lambda: export_prior_attendance_summary_csv(self.salon, NEXT, DAY)):
            with self.assertRaises(ValueError):
                call()

    def test_export_csv_and_dicts(self):
        self._book()
        rows = export_prior_attendance_summary(self.salon, DAY, DAY)
        self.assertEqual(list(rows[0].keys()), PRIOR_ATTENDANCE_SUMMARY_EXPORT_FIELDNAMES)
        # total + 3 staff + 1 per-day row
        self.assertEqual((len(rows), rows[0]["staff_name"], rows[0]["current_sessions_count"]), (5, "", 3))
        self.assertEqual([r["section"] for r in rows],
                         ["total", "staff", "staff", "staff", "day"])
        text = export_prior_attendance_summary_csv(self.salon, DAY, DAY)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0],
                         PRIOR_ATTENDANCE_SUMMARY_EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(text)))
        # CSV and dict exports agree row-for-row (values stringified).
        self.assertEqual(len(parsed), len(rows))
        self.assertEqual((parsed[0]["current_total_minutes"], parsed[0]["total_minutes_percent_change"],
                          parsed[0]["current_open_sessions"]), ("720", "0.00", "1"))
        one = next(r for r in parsed if r["staff_name"] == "Stylist One")
        self.assertEqual((one["total_minutes_percent_change"], one["prior_end_date"]),
                         ("-50.00", PRIOR_DAY.isoformat()))
        three = next(r for r in parsed if r["staff_name"] == "Stylist Three")
        self.assertEqual(three["sessions_count_percent_change"], "")
        # Per-day row agrees with the report's per_day entry.
        report = prior_attendance_summary_report(self.salon, DAY, DAY)
        day_row = next(r for r in rows if r["section"] == "day")
        entry = report.per_day[0]
        self.assertEqual((day_row["date"], day_row["prior_date"]),
                         (DAY.isoformat(), PRIOR_DAY.isoformat()))
        for m in ("sessions_count", "closed_sessions", "open_sessions",
                  "total_minutes", "staff_count"):
            d = getattr(entry, m)
            self.assertEqual((day_row[f"current_{m}"], day_row[f"prior_{m}"],
                              day_row[f"{m}_delta"]), (d.current, d.prior, d.delta))
        parsed_day = next(r for r in parsed if r["section"] == "day")
        self.assertEqual((parsed_day["current_total_minutes"],
                          parsed_day["current_staff_count"]), ("720", "3"))

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_attendance_summary", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), export_prior_attendance_summary_csv(self.salon, DAY, DAY))
        self.assertIn("day", [r["section"] for r in csv.DictReader(io.StringIO(out.getvalue()))])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            call_command("export_prior_attendance_summary", salon_id=self.salon.pk,
                         start_date="2026-11-02", end_date="2026-11-02", output=path)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), export_prior_attendance_summary_csv(self.salon, DAY, DAY))
        for kwargs in (dict(salon_id=self.salon.pk + 1000, start_date=DAY, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date=NEXT, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date="bad", end_date=DAY),
                       dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_prior_attendance_summary", stdout=io.StringIO(), **kwargs)
