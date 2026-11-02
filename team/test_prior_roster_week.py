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

    def test_export_csv_and_dicts(self):
        self._book()
        rows = export_prior_roster_week(self.salon, MONDAY)
        self.assertEqual(list(rows[0].keys()), PRIOR_ROSTER_WEEK_EXPORT_FIELDNAMES)
        self.assertEqual((len(rows), rows[0]["staff_name"], rows[0]["current_total_minutes"]), (4, "", 1680))
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
