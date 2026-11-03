"""Set one staff member's recurring roster pattern for one weekday.

Usage:
    python manage.py set_roster_pattern --staff-member-id ID
        --weekday 0 --start HH:MM --end HH:MM [--inactive]
        [--dry-run]
    python manage.py set_roster_pattern --staff-member-id ID
        --weekday Monday --start HH:MM --end HH:MM [--dry-run]

Thin wrapper around :mod:`team.roster_patterns`: the staff
member is resolved by id and the weekday/times are parsed,
then passed to the service verbatim -- its validation stays
the single source of truth and surfaces here as
``CommandError``. This command adds no pattern logic of its
own, so command and roster book can never disagree: the row
written is the perpetual ``RosterPattern``
``team.availability`` reads for that weekday, every week
(the switch-is-law ON write -- never a ``ShiftOverride``).

With ``--dry-run`` nothing is written and nothing is rolled
back: the preview is computed from reads only via
``preview_roster_pattern`` and printed. A write-then-rollback
preview is not NEDB-safe (``transaction.set_rollback`` does
not roll back on NEDB, DYOR section 9.4), so it is never used
here; the dry run of ``check_in`` is the house exemplar for
this reads-only shape.

Invalid input -- an unknown staff member, an unparseable or
out-of-range weekday/time, or a service ``ValidationError``
-- raises ``CommandError`` and nothing is written. Backend
only -- no views, templates, or UI.
"""
import argparse

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from team.models import RosterPattern, StaffMember
from team.roster_import import parse_time, parse_weekday
from team.roster_patterns import (
    preview_roster_pattern, set_roster_pattern,
)


def _parse_weekday(value):
    weekday = parse_weekday(value)
    if weekday is None:
        raise argparse.ArgumentTypeError(
            f"Invalid weekday {value!r}; expected 0-6 or a "
            f"weekday name.")
    return weekday


def _parse_time(value):
    parsed = parse_time(value)
    if parsed is None:
        raise argparse.ArgumentTypeError(
            f"Invalid time {value!r}; expected HH:MM.")
    return parsed


def _coerce_weekday(value):
    if value is None or isinstance(value, int) \
            and not isinstance(value, bool):
        return value
    weekday = parse_weekday(value)
    if weekday is None:
        raise CommandError(f"Invalid weekday {value!r}.")
    return weekday


def _coerce_time(value, kind):
    if value is None or not isinstance(value, str):
        return value
    parsed = parse_time(value)
    if parsed is None:
        raise CommandError(f"Invalid {kind} {value!r}.")
    return parsed


def _describe(member, weekday, start, end, active):
    return (f"RosterPattern staff_member={member} "
            f"staff_member_id={member.pk} weekday={weekday} "
            f"weekday_name="
            f"{RosterPattern.Weekday(weekday).label} "
            f"start_time={start} end_time={end} active={active}")


class Command(BaseCommand):
    help = ("Set one staff member's recurring roster pattern "
            "(perpetual, every week) for one weekday.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--staff-member-id", required=True, type=int,
            help="Id of the staff member whose pattern is set.")
        parser.add_argument(
            "--weekday", dest="weekday", type=_parse_weekday,
            default=None,
            help="Weekday ruled: 0 (Monday) to 6 (Sunday), or "
                 "a weekday name.")
        parser.add_argument(
            "--start", "--start-time", dest="start",
            type=_parse_time, default=None,
            help="Pattern start, HH:MM.")
        parser.add_argument(
            "--end", "--end-time", dest="end",
            type=_parse_time, default=None,
            help="Pattern end, HH:MM.")
        parser.add_argument(
            "--inactive", dest="inactive", action="store_true",
            help="Write the pattern inactive (availability "
                 "reads active patterns only).")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: compute what would change "
                 "from reads only, print it, write nothing.")

    def handle(self, *args, **options):
        try:
            member = StaffMember.objects.get(
                pk=options.get("staff_member_id"))
        except StaffMember.DoesNotExist:
            raise CommandError(
                f"No staff member with id "
                f"{options.get('staff_member_id')}.") from None
        weekday = _coerce_weekday(options.get("weekday"))
        if weekday is None:
            raise CommandError("Provide --weekday.")
        start = _coerce_time(
            options.get("start") or options.get("start_time"),
            "time")
        end = _coerce_time(
            options.get("end") or options.get("end_time"), "time")
        active = not bool(options.get("inactive"))
        dry_run = bool(options.get("dry_run"))
        if dry_run:
            try:
                preview = preview_roster_pattern(
                    member, weekday, start_time=start,
                    end_time=end, active=active)
            except ValidationError as exc:
                raise CommandError(
                    "; ".join(exc.messages)) from exc
            self.stdout.write(
                f"Dry run: would set "
                f"{_describe(member, preview['weekday'], preview['start_time'], preview['end_time'], preview['active'])} "
                f"replacing "
                f"{len(preview['existing'])} existing "
                f"pattern(s) -- no pattern written.")
            return
        try:
            pattern = set_roster_pattern(
                member, weekday, start_time=start, end_time=end,
                active=active)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(
            "Set " + _describe(
                member, pattern.weekday, pattern.start_time,
                pattern.end_time, pattern.active) + ".")
