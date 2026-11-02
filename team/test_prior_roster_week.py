"""Tests for prior-week roster week: service, CSV export, command."""
import csv
import datetime
import io
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon
from team.models import RosterPattern, ShiftOverride, StaffMember
from team.prior_roster_week import prior_roster_week_report
from team.prior_roster_week_export import (
    PRIOR_ROSTER_WEEK_EXPORT_FIELDNAMES, export_prior_roster_week,
    export_prior_roster_week_csv)
from team.roster_week import roster_week

MONDAY = datetime.date(2026, 11, 2)  # Monday (current week)
PRIOR_MONDAY = datetime.date(2026, 10, 26)
PRIOR_SUNDAY = datetime.date(2026, 11, 1)
SUNDAY = datetime.date(2026, 11, 8)


class PriorRosterWeekTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.one = StaffMember.objects.create(salon=self.salon, display_name="Stylist One")
        self.two = StaffMember.objects.create(salon=self.salon, display_name="Stylist Two")
        self.three = StaffMember.objects.create(salon=self.salon, display_name="Stylist Three")
        # One: Mon 9-17 (480) + Wed 9-13 (240) = 720 / 2 days each week.
        RosterPattern.objects.create(staff_member=self.one, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0))
        RosterPattern.objects.create(staff_member=self.one, weekday=2,
            start_time=datetime.time(9, 0), end_time=datetime.time(13, 0))
        # Two: Mon 9-17 = 480 / 1 day each week.
        RosterPattern.objects.create(staff_member=self.two, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0))
        # Three: Tue 9-17 = 480 / 1 day each week.
        RosterPattern.objects.create(staff_member=self.three, weekday=1,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0))

    def _book(self):
        # Prior week only: One's Monday is a short shift (240 not 480);
        # Two is off on prior Monday (0 / 0 days that week).
        ShiftOverride.objects.create(staff_member=self.one, date=PRIOR_MONDAY,
            start_time=datetime.time(9, 0), end_time=datetime.time(13, 0))
        ShiftOverride.objects.create(staff_member=self.two, date=PRIOR_MONDAY, is_off=True)

    def test_both_weeks_verbatim_and_totals(self):
        self._book()
        r = prior_roster_week_report(self.salon, MONDAY)
        self.assertEqual((r.week_start, r.week_end, r.prior_week_start, r.prior_week_end),
                         (MONDAY, SUNDAY, PRIOR_MONDAY, PRIOR_SUNDAY))
        self.assertEqual((r.start_date, r.prior_start_date), (MONDAY, PRIOR_MONDAY))
        self.assertEqual(r.current, roster_week(self.salon, MONDAY))
        self.assertEqual(r.prior, roster_week(self.salon, PRIOR_MONDAY))
        # Salon: current 720+480+480=1680 / 4d; prior 480+0+480=960 / 3d.
        self.assertEqual((r.total_minutes.current, r.total_minutes.prior,
                          r.total_minutes.delta, r.total_minutes.percent_change),
                         (1680, 960, 720, Decimal("75.00")))
        self.assertEqual((r.working_days.current, r.working_days.prior,
                          r.working_days.delta, r.working_days.percent_change),
                         (4, 3, 1, Decimal("33.33")))
        self.assertEqual(r.as_dict()["total_minutes"]["delta"], 720)

    def test_per_staff_deltas_and_union(self):
        self._book()
        r = prior_roster_week_report(self.salon, MONDAY)
        self.assertEqual([s.staff_name for s in r.by_staff],
                         ["Stylist One", "Stylist Three", "Stylist Two"])
        one = r.for_staff(self.one)
        self.assertEqual((one.total_minutes.current, one.total_minutes.prior,
                          one.total_minutes.delta, one.total_minutes.percent_change),
                         (720, 480, 240, Decimal("50.00")))
        self.assertEqual((one.working_days.current, one.working_days.delta), (2, 0))
        three = r.for_staff(self.three)
        self.assertEqual((three.total_minutes.current, three.total_minutes.prior,
                          three.total_minutes.percent_change), (480, 480, Decimal("0.00")))

    def test_zero_prior_side(self):
        self._book()
        r = prior_roster_week_report(self.salon, MONDAY)
        two = r.for_staff(self.two)
        # Prior side is zero (off that week): figures are 0, percent None.
        self.assertEqual((two.total_minutes.current, two.total_minutes.prior,
                          two.total_minutes.delta, two.working_days.prior), (480, 0, 480, 0))
        self.assertIsNone(two.total_minutes.percent_change)
        self.assertIsNone(two.working_days.percent_change)

    def test_empty_salon_non_monday_snap_and_errors(self):
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        r = prior_roster_week_report(empty, MONDAY)
        self.assertEqual(r.by_staff, ())
        self.assertEqual((r.total_minutes.current, r.total_minutes.delta), (0, 0))
        self.assertIsNone(r.total_minutes.percent_change)
        wed = MONDAY + datetime.timedelta(days=2)
        self.assertEqual(prior_roster_week_report(self.salon, wed).week_start, MONDAY)
        self.assertEqual(prior_roster_week_report(self.salon, week_start="2026-11-02").week_start, MONDAY)
        for call in (lambda: prior_roster_week_report(None, MONDAY),
                     lambda: prior_roster_week_report(self.salon),
                     lambda: prior_roster_week_report(self.salon, None),
                     lambda: prior_roster_week_report(self.salon, "bad"),
                     lambda: export_prior_roster_week_csv(self.salon, "bad")):
            with self.assertRaises(ValueError):
                call()

    def test_by_weekday_deltas(self):
        self._book()
        r = prior_roster_week_report(self.salon, MONDAY)
        self.assertEqual([w.weekday for w in r.by_weekday], list(range(7)))
        self.assertEqual([w.weekday_name for w in r.by_weekday],
                         ["Monday", "Tuesday", "Wednesday", "Thursday",
                          "Friday", "Saturday", "Sunday"])
        self.assertEqual(r.weekdays, r.by_weekday)
        mon = r.for_weekday(0)
        self.assertIs(mon, r.for_weekday("monday"))
        # Mon: current One 480 + Two 480; prior One override 240, Two off.
        self.assertEqual((mon.day, mon.prior_day), (MONDAY, PRIOR_MONDAY))
        self.assertEqual((mon.total_minutes.current, mon.total_minutes.prior,
                          mon.total_minutes.delta, mon.total_minutes.percent_change),
                         (960, 240, 720, Decimal("300.00")))
        self.assertEqual((mon.working_staff.current, mon.working_staff.prior,
                          mon.working_staff.delta, mon.working_staff.percent_change),
                         (2, 1, 1, Decimal("100.00")))
        self.assertEqual((mon.current.total_minutes, mon.prior.working_staff), (960, 1))
        tue, wed = r.for_weekday(1), r.for_weekday("Wednesday")
        self.assertEqual((tue.total_minutes.current, tue.total_minutes.delta,
                          tue.working_staff.current), (480, 0, 1))
        self.assertEqual((wed.total_minutes.current, wed.total_minutes.prior,
                          wed.total_minutes.percent_change), (240, 240, Decimal("0.00")))
        sun = r.for_weekday(6)
        self.assertEqual((sun.day, sun.prior_day, sun.total_minutes.current,
                          sun.working_staff.current), (SUNDAY, PRIOR_SUNDAY, 0, 0))
        self.assertIsNone(sun.total_minutes.percent_change)
        self.assertIsNone(sun.working_staff.percent_change)
        # Weekday minutes sum back to the salon totals on both sides.
        self.assertEqual(sum(w.total_minutes.current for w in r.by_weekday), 1680)
        self.assertEqual(sum(w.total_minutes.prior for w in r.by_weekday), 960)
        d = r.as_dict()["by_weekday"]
        self.assertEqual((len(d), d[0]["weekday_name"], d[0]["total_minutes"]["delta"],
                          d[0]["working_staff"]["current"]), (7, "Monday", 720, 2))

    def test_by_weekday_empty_salon(self):
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        r = prior_roster_week_report(empty, MONDAY)
        self.assertEqual(len(r.by_weekday), 7)
        for w in r.by_weekday:
            self.assertEqual((w.total_minutes.current, w.total_minutes.prior,
                              w.working_staff.current, w.working_staff.prior), (0, 0, 0, 0))
            self.assertIsNone(w.total_minutes.percent_change)

    def test_export_csv_and_dicts(self):
        self._book()
        rows = export_prior_roster_week(self.salon, MONDAY)
        self.assertEqual(list(rows[0].keys()), PRIOR_ROSTER_WEEK_EXPORT_FIELDNAMES)
        self.assertEqual((len(rows), rows[0]["staff_name"], rows[0]["current_total_minutes"]), (11, "", 1680))
        self.assertEqual([row["section"] for row in rows],
                         ["total"] + ["staff"] * 3 + ["weekday"] * 7)
        mon = next(row for row in rows if row["section"] == "weekday" and row["weekday_name"] == "Monday")
        self.assertEqual((mon["weekday"], mon["date"], mon["prior_date"],
                          mon["current_total_minutes"], mon["prior_total_minutes"],
                          mon["total_minutes_delta"], mon["total_minutes_percent_change"],
                          mon["current_working_staff"], mon["prior_working_staff"],
                          mon["working_staff_delta"], mon["current_working_days"]),
                         (0, MONDAY.isoformat(), PRIOR_MONDAY.isoformat(),
                          960, 240, 720, "300.00", 2, 1, 1, ""))
        self.assertEqual(rows[0]["current_working_staff"], "")
        text = export_prior_roster_week_csv(self.salon, MONDAY)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0], PRIOR_ROSTER_WEEK_EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual((parsed[0]["current_total_minutes"], parsed[0]["total_minutes_percent_change"],
                          parsed[0]["prior_week_start"], parsed[0]["working_days_percent_change"]),
                         ("1680", "75.00", PRIOR_MONDAY.isoformat(), "33.33"))
        two = next(r for r in parsed if r["staff_name"] == "Stylist Two")
        self.assertEqual((two["prior_total_minutes"], two["total_minutes_percent_change"]), ("0", ""))

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_roster_week", salon_id=self.salon.pk, week_start=MONDAY, stdout=out)
        self.assertEqual(out.getvalue(), export_prior_roster_week_csv(self.salon, MONDAY))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            call_command("export_prior_roster_week", salon_id=self.salon.pk,
                         week_start="2026-11-02", output=path)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), export_prior_roster_week_csv(self.salon, MONDAY))
        for kwargs in (dict(salon_id=self.salon.pk + 1000, week_start=MONDAY),
                       dict(salon_id=self.salon.pk, week_start="bad"),
                       dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_prior_roster_week", stdout=io.StringIO(), **kwargs)
