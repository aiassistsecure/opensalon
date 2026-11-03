"""Set or clear one staff member's shift override for one date.

Usage:
    python manage.py set_shift_override --staff-member-id ID
        --date YYYY-MM-DD --start HH:MM --end HH:MM [--dry-run]
    python manage.py set_shift_override --staff-member-id ID
        --date YYYY-MM-DD --off [--dry-run]
    python manage.py set_shift_override --staff-member-id ID
        --date YYYY-MM-DD --clear [--dry-run]

Thin wrapper around :mod:`team.shift_overrides`: the staff
member is resolved by id and the date/times are parsed, then
passed to the service verbatim -- its shape validation stays
the single source of truth and surfaces here as
``CommandError``. This command adds no override logic of its
own, so command and roster book can never disagree: the row
written is the row ``team.availability`` (override-first)
reads. ``--clear`` is the undo: the override is deleted and
the perpetual pattern rules the date again.

With ``--dry-run`` nothing is written: the command calls
the service's validate-only helper (for the set path) or
reads whether an override exists (for ``--clear``), prints
the override that WOULD apply (or be removed), and returns
before any writer runs -- no write happens at all, so the
preview is safe on every backend (NEDB does not roll back
transaction writes).

Invalid input -- an unknown staff member, an unparseable
date/time, a conflicting or incomplete shape, or a service
``ValidationError`` -- raises ``CommandError`` and nothing
is written. Backend only -- no views, templates, or UI.
"""
import argparse
import datetime

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from team.models import ShiftOverride, StaffMember
from team.shift_overrides import (
    clear_shift_override, set_shift_override,
    validate_set_shift_override,
)


def _date_from_string(value):
    return datetime.date.fromisoformat(str(value).strip())


def _time_from_string(value):
    return datetime.time.fromisoformat(str(value).strip())


def _parse_date(value):
    try:
        return _date_from_string(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _parse_time(value):
    try:
        return _time_from_string(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid time {value!r}; expected HH:MM."
        ) from exc


def _coerce(value, conv, kind):
    if value is None or not isinstance(value, str):
        return value
    try:
        return conv(value)
    except ValueError as exc:
        raise CommandError(
            f"Invalid {kind} {value!r}.") from exc


def _describe(member, day, is_off, start, end):
    if is_off:
        return (f"ShiftOverride staff_member={member} "
                f"staff_member_id={member.pk} date={day} "
                f"is_off=True start_time=None end_time=None")
    return (f"ShiftOverride staff_member={member} "
            f"staff_member_id={member.pk} date={day} "
            f"is_off=False start_time={start} end_time={end}")


class Command(BaseCommand):
    help = ("Set (placed shift or full day off) or clear one "
            "staff member's shift override for one date.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--staff-member-id", required=True, type=int,
            help="Id of the staff member whose date is ruled.")
        parser.add_argument(
            "--date", dest="date", type=_parse_date, default=None,
            help="The one date ruled, YYYY-MM-DD.")
        parser.add_argument(
            "--start", "--start-time", dest="start",
            type=_parse_time, default=None,
            help="Placed shift start, HH:MM.")
        parser.add_argument(
            "--end", "--end-time", dest="end",
            type=_parse_time, default=None,
            help="Placed shift end, HH:MM.")
        parser.add_argument(
            "--off", dest="is_off", action="store_true",
            help="Rule the full day off (no times).")
        parser.add_argument(
            "--clear", dest="clear", action="store_true",
            help="Undo: delete the date's override so the "
                 "perpetual pattern rules it again.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: validate without writing, "
                 "print the override that would apply (or, "
                 "with --clear, that would be removed), and "
                 "write nothing.")

    def handle(self, *args, **options):
        try:
            member = StaffMember.objects.get(
                pk=options.get("staff_member_id"))
        except StaffMember.DoesNotExist:
            raise CommandError(
                f"No staff member with id "
                f"{options.get('staff_member_id')}.") from None
        day = _coerce(options.get("date"), _date_from_string,
                      "date")
        if day is None:
            raise CommandError("Provide --date.")
        start = _coerce(options.get("start") or options.get(
            "start_time"), _time_from_string, "time")
        end = _coerce(options.get("end") or options.get(
            "end_time"), _time_from_string, "time")
        is_off = bool(options.get("is_off") or options.get("off"))
        clear = bool(options.get("clear"))
        if clear and (is_off or start is not None or end is not None):
            raise CommandError(
                "--clear cannot be combined with --off, "
                "--start, or --end.")
        dry_run = bool(options.get("dry_run"))
        if clear:
            if dry_run:
                removed = ShiftOverride.objects.filter(
                    staff_member=member, date=day).exists()
                self.stdout.write(
                    f"Dry run: would clear ShiftOverride "
                    f"staff_member_id={member.pk} date={day} "
                    f"({'an override exists' if removed else 'no override exists'}) "
                    f"-- no override cleared.")
                return
            removed = clear_shift_override(member, day)
            self.stdout.write(
                f"Cleared shift override for {member} on {day}."
                if removed else
                f"No shift override for {member} on {day} "
                f"to clear.")
            return
        if dry_run:
            try:
                v_day, v_off, v_start, v_end = (
                    validate_set_shift_override(
                        member, day, start_time=start,
                        end_time=end, is_off=is_off))
            except ValidationError as exc:
                raise CommandError(
                    "; ".join(exc.messages)) from exc
            preview = _describe(member, v_day, v_off, v_start, v_end)
            self.stdout.write(
                f"Dry run: would set {preview} "
                f"-- no override written.")
            return
        try:
            override = set_shift_override(
                member, day, start_time=start, end_time=end,
                is_off=is_off)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(
            "Set " + _describe(
                member, override.date, override.is_off,
                override.start_time, override.end_time) + ".")
