"""Record a staff member's check-in.

Usage:
    python manage.py check_in --staff-member-id ID
        [--at ISO-8601-DATETIME] [--note TEXT] [--dry-run]

With ``--dry-run`` the same validation runs and the
``AttendanceRecord`` that would be written is printed, but
no record is created.

Thin wrapper around :func:`team.availability.check_in`: the
staff member is resolved by id, ``--at`` is parsed to a
datetime, and both are passed to the service verbatim with
the note. This command adds no attendance logic of its own,
so command and service state can never disagree -- one
source of truth.

Invalid input -- an unknown staff member or an unparseable
datetime -- raises ``CommandError``; a service ``ValueError``
(e.g. already checked in) is also surfaced as ``CommandError``.
Backend only -- no views, templates, or UI.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from django.utils import timezone

from team.availability import check_in
from team.models import AttendanceRecord, StaffMember


def _datetime_from_string(value):
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(text)


def _parse_datetime(value):
    try:
        return _datetime_from_string(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid datetime {value!r}; expected ISO-8601."
        ) from exc


def _coerce_at(value):
    if value is None or isinstance(value, datetime.datetime):
        return value
    try:
        return _datetime_from_string(value)
    except ValueError as exc:
        raise CommandError(
            f"Invalid datetime {value!r}; expected ISO-8601."
        ) from exc


class Command(BaseCommand):
    help = "Record a check-in for one staff member."

    def add_arguments(self, parser):
        parser.add_argument(
            "--staff-member-id", required=True, type=int,
            help="Id of the staff member to check in.")
        parser.add_argument(
            "--at", dest="at", type=_parse_datetime, default=None,
            help="When the check-in happened, ISO-8601 "
                 "(default: now, per the service).")
        parser.add_argument(
            "--note", default="",
            help="Optional note recorded on the attendance event.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview the AttendanceRecord that would be "
                 "written and write nothing.")

    def handle(self, *args, **options):
        try:
            staff_member = StaffMember.objects.get(
                pk=options["staff_member_id"])
        except StaffMember.DoesNotExist:
            raise CommandError(
                f"No staff member with id "
                f"{options['staff_member_id']}.") from None
        recorded_at = _coerce_at(options.get("at"))
        if options.get("dry_run"):
            if staff_member.is_checked_in():
                raise CommandError(
                    f"{staff_member} is already checked in")
            when = recorded_at or timezone.now()
            self.stdout.write(
                f"Dry run: would create AttendanceRecord "
                f"staff_member={staff_member} "
                f"staff_member_id={staff_member.pk} "
                f"event_type={AttendanceRecord.EventType.CHECK_IN} "
                f"recorded_at={when} "
                f"note={options.get('note') or ''!r} "
                f"-- no record written.")
            return
        try:
            record = check_in(
                staff_member, recorded_at=recorded_at,
                note=options.get("note") or "")
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Checked in {record.staff_member} "
            f"at {record.recorded_at}.")
