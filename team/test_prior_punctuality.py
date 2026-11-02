"""Tests for prior-period punctuality: service, CSV export, command."""
import csv
import datetime
import io
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon
from team.models import AttendanceRecord, RosterPattern, StaffMember
from team.prior_punctuality import prior_punctuality_report
from team.prior_punctuality_export import (
    PRIOR_PUNCTUALITY_EXPORT_FIELDNAMES, export_prior_punctuality,
    export_prior_punctuality_csv)
from team.punctuality import punctuality_report

DAY = datetime.date(2026, 11, 2)  # Monday (current)
PRIOR_DAY = datetime.date(2026, 11, 1)  # Sunday (prior)
NEXT = datetime.date(2026, 11, 3)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class PriorPunctualityTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(salon=self.salon, display_name="Stylist One")
        self.other = StaffMember.objects.create(salon=self.salon, display_name="Stylist Two")
        self.monday_only = StaffMember.objects.create(salon=self.salon, display_name="Stylist Three")
        for member in (self.staff, self.other):
            for weekday in range(7):
                RosterPattern.objects.create(staff_member=member, weekday=weekday,
                    start_time=datetime.time(9, 0), end_time=datetime.time(17, 0))
        RosterPattern.objects.create(staff_member=self.monday_only, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0))

    def _check_in(self, staff, day, hour, minute=0):
        return AttendanceRecord.objects.create(staff_member=staff, event_type="check_in",
                                               recorded_at=at(day, hour, minute))

    def _book(self):
        self._check_in(self.staff, PRIOR_DAY, 9, 0)   # prior: on time
        self._check_in(self.other, PRIOR_DAY, 9, 30)  # prior: late 30
        self._check_in(self.staff, DAY, 9, 10)        # current: late 10
        self._check_in(self.monday_only, DAY, 9, 0)   # current: on time; Two missed

    def test_both_windows_verbatim_and_totals(self):
        self._book()
        r = prior_punctuality_report(self.salon, DAY, DAY)
        self.assertEqual((r.start_date, r.prior_start_date, r.prior_end_date), (DAY, PRIOR_DAY, PRIOR_DAY))
        self.assertEqual(r.days, 1)
        self.assertEqual(r.current, punctuality_report(self.salon, DAY, DAY))
        self.assertEqual(r.prior, punctuality_report(self.salon, PRIOR_DAY, PRIOR_DAY))
        self.assertEqual((r.shifts_considered.current, r.shifts_considered.prior,
                          r.shifts_considered.delta, r.shifts_considered.percent_change),
                         (3, 2, 1, Decimal("50.00")))
        self.assertEqual((r.on_time_count.current, r.on_time_count.prior, r.on_time_count.delta), (1, 1, 0))
        self.assertEqual((r.missed_count.current, r.missed_count.delta, r.missed_count.percent_change), (1, 1, None))
        self.assertEqual((r.total_late_minutes.current, r.total_late_minutes.prior,
                          r.total_late_minutes.delta, r.total_late_minutes.percent_change),
                         (10, 30, -20, Decimal("-66.67")))
        self.assertEqual((r.average_late_minutes.current, r.average_late_minutes.prior,
                          r.average_late_minutes.delta, r.average_late_minutes.percent_change),
                         (Decimal("10.00"), Decimal("30.00"), Decimal("-20.00"), Decimal("-66.67")))
        self.assertEqual(r.as_dict()["total_late_minutes"]["delta"], -20)

    def test_per_staff_deltas_and_union(self):
        self._book()
        r = prior_punctuality_report(self.salon, DAY, DAY)
        self.assertEqual([s.staff_name for s in r.by_staff], ["Stylist One", "Stylist Three", "Stylist Two"])
        one = r.for_staff(self.staff)
        self.assertEqual((one.late_count.current, one.late_count.prior, one.late_count.percent_change), (1, 0, None))
        two = r.for_staff(self.other)
        self.assertEqual((two.missed_count.current, two.total_late_minutes.delta,
                          two.total_late_minutes.percent_change), (1, -30, Decimal("-100.00")))
        three = r.for_staff(self.monday_only)
        self.assertEqual((three.shifts_considered.current, three.shifts_considered.prior,
                          three.on_time_count.current), (1, 0, 1))
        self.assertIsNone(three.shifts_considered.percent_change)

    def test_zero_prior_and_empty(self):
        other = Salon.objects.create(name="Other", timezone="UTC")
        r = prior_punctuality_report(other, DAY, DAY)
        self.assertEqual(r.by_staff, ())
        self.assertIsNone(r.shifts_considered.percent_change)
        self.assertEqual(r.average_late_minutes.delta, Decimal("0.00"))
        self.assertIsNone(r.average_late_minutes.percent_change)

    def test_equal_length_aliases_and_errors(self):
        self._book()
        start = DAY - datetime.timedelta(days=6)
        r = prior_punctuality_report(self.salon, start_date=start, end_date=DAY)
        self.assertEqual((r.days, r.prior_start_date, r.prior_end_date),
                         (7, start - datetime.timedelta(days=7), start - datetime.timedelta(days=1)))
        self.assertEqual(prior_punctuality_report(self.salon, DAY).shifts_considered.current, 3)
        for call in (lambda: prior_punctuality_report(self.salon, NEXT, DAY),
                     lambda: prior_punctuality_report(None, DAY, DAY),
                     lambda: prior_punctuality_report(self.salon),
                     lambda: export_prior_punctuality_csv(self.salon, NEXT, DAY)):
            with self.assertRaises(ValueError):
                call()

    def test_export_csv_and_dicts(self):
        self._book()
        rows = export_prior_punctuality(self.salon, DAY, DAY)
        self.assertEqual(list(rows[0].keys()), PRIOR_PUNCTUALITY_EXPORT_FIELDNAMES)
        self.assertEqual((len(rows), rows[0]["staff_name"], rows[0]["current_shifts_considered"]), (4, "", 3))
        text = export_prior_punctuality_csv(self.salon, DAY, DAY)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0], PRIOR_PUNCTUALITY_EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual((parsed[0]["current_total_late_minutes"], parsed[0]["total_late_minutes_percent_change"],
                          parsed[0]["current_average_late_minutes"], parsed[0]["average_late_minutes_delta"]),
                         ("10", "-66.67", "10.00", "-20.00"))
        one = next(r for r in parsed if r["staff_name"] == "Stylist One")
        self.assertEqual((one["late_count_percent_change"], one["prior_end_date"]), ("", PRIOR_DAY.isoformat()))

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_punctuality", salon_id=self.salon.pk, start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), export_prior_punctuality_csv(self.salon, DAY, DAY))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            call_command("export_prior_punctuality", salon_id=self.salon.pk,
                         start_date="2026-11-02", end_date="2026-11-02", output=path)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), export_prior_punctuality_csv(self.salon, DAY, DAY))
        for kwargs in (dict(salon_id=self.salon.pk + 1000, start_date=DAY, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date=NEXT, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date="bad", end_date=DAY),
                       dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_prior_punctuality", stdout=io.StringIO(), **kwargs)
