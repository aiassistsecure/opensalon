"""Tests for prior-period variance: service, CSV export, command."""
import csv
import datetime
import io
import json
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from saloncore.models import Salon
from team.models import AttendanceRecord, RosterPattern, StaffMember
from team.prior_variance import prior_variance_report
from team.prior_variance_export import (
    PRIOR_VARIANCE_EXPORT_FIELDNAMES, export_prior_variance,
    export_prior_variance_csv)
from team.variance import roster_variance

DAY = datetime.date(2026, 11, 2)  # Monday (current)
PRIOR_DAY = datetime.date(2026, 11, 1)  # Sunday (prior)
NEXT = datetime.date(2026, 11, 3)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class PriorVarianceTests(TestCase):
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

    def _session(self, staff, day, start=(9, 0), end=(17, 0)):
        for kind, when in (("check_in", start), ("check_out", end)):
            AttendanceRecord.objects.create(staff_member=staff, event_type=kind, recorded_at=at(day, *when))

    def _book(self):
        self._session(self.staff, PRIOR_DAY)                    # prior: 480 actual
        self._session(self.other, PRIOR_DAY, end=(13, 0))       # prior: 240 actual
        self._session(self.staff, DAY, end=(13, 0))             # current: 240 actual
        self._session(self.monday_only, DAY)                    # current: 480; Two absent

    def test_both_windows_verbatim_and_totals(self):
        self._book()
        r = prior_variance_report(self.salon, DAY, DAY)
        self.assertEqual((r.start_date, r.prior_start_date, r.prior_end_date), (DAY, PRIOR_DAY, PRIOR_DAY))
        self.assertEqual(r.days, 1)
        self.assertEqual(r.current, roster_variance(self.salon, DAY, DAY))
        self.assertEqual(r.prior, roster_variance(self.salon, PRIOR_DAY, PRIOR_DAY))
        self.assertEqual((r.rostered_minutes.current, r.rostered_minutes.prior,
                          r.rostered_minutes.delta, r.rostered_minutes.percent_change),
                         (1440, 960, 480, Decimal("50.00")))
        self.assertEqual((r.actual_minutes.current, r.actual_minutes.prior,
                          r.actual_minutes.delta, r.actual_minutes.percent_change),
                         (720, 720, 0, Decimal("0.00")))
        self.assertEqual((r.variance_minutes.current, r.variance_minutes.prior,
                          r.variance_minutes.delta, r.variance_minutes.percent_change),
                         (-720, -240, -480, Decimal("200.00")))
        self.assertEqual((r.days_rostered.current, r.days_rostered.delta), (3, 1))
        self.assertEqual((r.days_attended.current, r.days_attended.prior), (2, 2))
        self.assertEqual((r.absence_days.current, r.absence_days.delta,
                          r.absence_days.percent_change), (1, 1, None))
        self.assertEqual(r.as_dict()["rostered_minutes"]["delta"], 480)

    def test_per_staff_deltas_and_union(self):
        self._book()
        r = prior_variance_report(self.salon, DAY, DAY)
        self.assertEqual([s.staff_name for s in r.by_staff],
                         ["Stylist One", "Stylist Three", "Stylist Two"])
        one = r.for_staff(self.staff)
        self.assertEqual((one.actual_minutes.current, one.actual_minutes.prior,
                          one.actual_minutes.delta, one.actual_minutes.percent_change),
                         (240, 480, -240, Decimal("-50.00")))
        self.assertIsNone(one.variance_minutes.percent_change)  # prior variance 0
        two = r.for_staff(self.other)
        self.assertEqual((two.absence_days.current, two.variance_minutes.delta,
                          two.variance_minutes.percent_change), (1, -240, Decimal("100.00")))
        three = r.for_staff(self.monday_only)
        self.assertEqual((three.rostered_minutes.current, three.rostered_minutes.prior,
                          three.actual_minutes.current, three.days_rostered.current), (480, 0, 480, 1))
        self.assertIsNone(three.rostered_minutes.percent_change)

    def test_zero_prior_and_empty(self):
        other = Salon.objects.create(name="Other", timezone="UTC")
        r = prior_variance_report(other, DAY, DAY)
        self.assertEqual(r.by_staff, ())
        self.assertEqual((r.rostered_minutes.current, r.rostered_minutes.delta), (0, 0))
        self.assertIsNone(r.rostered_minutes.percent_change)

    def test_equal_length_aliases_and_errors(self):
        self._book()
        start = DAY - datetime.timedelta(days=6)
        r = prior_variance_report(self.salon, start_date=start, end_date=DAY)
        self.assertEqual((r.days, r.prior_start_date, r.prior_end_date),
                         (7, start - datetime.timedelta(days=7), start - datetime.timedelta(days=1)))
        self.assertEqual(prior_variance_report(self.salon, DAY).rostered_minutes.current, 1440)
        for call in (lambda: prior_variance_report(self.salon, NEXT, DAY),
                     lambda: prior_variance_report(None, DAY, DAY),
                     lambda: prior_variance_report(self.salon),
                     lambda: export_prior_variance_csv(self.salon, NEXT, DAY)):
            with self.assertRaises(ValueError):
                call()

    def test_export_csv_and_dicts(self):
        self._book()
        rows = export_prior_variance(self.salon, DAY, DAY)
        self.assertEqual(list(rows[0].keys()), PRIOR_VARIANCE_EXPORT_FIELDNAMES)
        self.assertEqual((len(rows), rows[0]["staff_name"], rows[0]["current_rostered_minutes"]), (4, "", 1440))
        text = export_prior_variance_csv(self.salon, DAY, DAY)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0], PRIOR_VARIANCE_EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual((parsed[0]["current_rostered_minutes"], parsed[0]["rostered_minutes_percent_change"],
                          parsed[0]["current_variance_minutes"], parsed[0]["variance_minutes_delta"]),
                         ("1440", "50.00", "-720", "-480"))
        one = next(r for r in parsed if r["staff_name"] == "Stylist One")
        self.assertEqual((one["actual_minutes_percent_change"], one["prior_end_date"]), ("-50.00", PRIOR_DAY.isoformat()))
        three = next(r for r in parsed if r["staff_name"] == "Stylist Three")
        self.assertEqual(three["rostered_minutes_percent_change"], "")

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_variance", salon_id=self.salon.pk, start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), export_prior_variance_csv(self.salon, DAY, DAY))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            call_command("export_prior_variance", salon_id=self.salon.pk,
                         start_date="2026-11-02", end_date="2026-11-02", output=path)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), export_prior_variance_csv(self.salon, DAY, DAY))
        for kwargs in (dict(salon_id=self.salon.pk + 1000, start_date=DAY, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date=NEXT, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date="bad", end_date=DAY),
                       dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_prior_variance", stdout=io.StringIO(), **kwargs)

    def test_command_default_and_explicit_csv_match_service(self):
        self._book()
        want = export_prior_variance_csv(self.salon, DAY, DAY)
        out = io.StringIO()
        call_command("export_prior_variance", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        call_command("export_prior_variance", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, format="csv", stdout=out)
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        call_command("export_prior_variance",
                     "--salon-id", str(self.salon.pk),
                     "--start-date", str(DAY), "--end-date", str(DAY),
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), want)

    def test_command_json_parses_and_equals_dict_service_rows(self):
        self._book()
        rows = export_prior_variance(self.salon, DAY, DAY)
        out = io.StringIO()
        call_command("export_prior_variance", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(
            out.getvalue(),
            json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")
        parsed = json.loads(out.getvalue())
        one = next(r for r in parsed if r["staff_name"] == "Stylist One")
        self.assertEqual((one["current_actual_minutes"],
                          one["actual_minutes_percent_change"]),
                         (240, "-50.00"))
        self.assertEqual(one["prior_end_date"], PRIOR_DAY.isoformat())

    def test_command_json_flag_matches_dict_service(self):
        out = io.StringIO()
        call_command("export_prior_variance",
                     "--salon-id", str(self.salon.pk),
                     "--start-date", str(DAY), "--end-date", str(DAY),
                     "--format", "json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         export_prior_variance(self.salon, DAY, DAY))

    def test_command_json_output_file_matches_dict_service(self):
        self._book()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior.json")
            out = io.StringIO()
            call_command("export_prior_variance", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY, format="json",
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(json.loads(written),
                         export_prior_variance(self.salon, DAY, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_command_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_variance", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY, format="xml",
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_variance",
                         "--salon-id", str(self.salon.pk),
                         "--start-date", str(DAY), "--end-date", str(DAY),
                         "--format", "xml", stdout=io.StringIO())
