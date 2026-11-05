"""Export one salon's attendance records as CSV.

Usage:
    python manage.py export_attendance_records --salon-id ID
        [--staff-member-id ID]
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--event-type EVENT_TYPE]
        [--output PATH]

Thin wrapper around the existing
:func:`team.attendance_record_export.export_attendance_records_csv`
service: the salon is resolved by id and passed to the service
verbatim -- its CSV text is written unchanged, to ``--output``
when given and to stdout otherwise. This command adds no
export logic of its own, so command and service output can
never disagree -- one source of truth.

With ``--staff-member-id`` the export is narrowed to that one
staff member's attendance records: the staff member is resolved
by id within the salon (a staff member from another salon, or
an unknown id, is a ``CommandError``), and the resolved staff
member is passed to the service as its optional
``staff_member`` argument. Without ``--staff-member-id`` the
command exports the whole salon, exactly as before.

With ``--start-date`` / ``--end-date`` (spelled exactly as
``export_attendance`` spells them) the export is narrowed to
records whose ``recorded_at`` falls in that window: the
dates are parsed to ``datetime.date`` objects and passed to
the service as its optional ``start`` / ``end`` arguments,
so a date start means the start of that day and a date end
includes the whole end day. Each bound is optional; without
either, the command exports every record, exactly as
before. The window composes with ``--staff-member-id``
(window AND record).

With ``--event-type`` the export is narrowed to records
whose stored event type exactly matches it (the
``AttendanceRecord.EventType`` slugs ``check_in`` /
``check_out``): the value is passed to the service as its
optional ``event_type`` argument. Without ``--event-type``
the command exports every event type, exactly as before.
It composes with ``--staff-member-id`` and the date window
(all AND).

An unknown salon, an unparseable date, or a reversed range
raises ``CommandError``. Backend only -- no views,
templates, or UI. Read-only.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from team.attendance_record_export import export_attendance_records_csv
from team.models import StaffMember


def _parse_date(value, label):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export one salon's attendance records as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose attendance records to export.")
        parser.add_argument(
            "--staff-member-id", type=int, default=None,
            help="ID of the staff member (in the salon) whose "
                 "attendance records to export "
                 "(default: all staff members).")
        parser.add_argument(
            "--start-date", dest="start_date", default=None,
            help="First day of the range, YYYY-MM-DD (inclusive; "
                 "default: unbounded).")
        parser.add_argument(
            "--end-date", dest="end_date", default=None,
            help="Last day of the range, YYYY-MM-DD (inclusive; "
                 "default: unbounded).")
        parser.add_argument(
            "--event-type", dest="event_type", default=None,
            help="Event type value to filter by (default: "
                 "all event types).")
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        staff_member = None
        if options.get("staff_member_id") is not None:
            try:
                staff_member = StaffMember.objects.get(
                    pk=options["staff_member_id"], salon=salon
                )
            except StaffMember.DoesNotExist:
                raise CommandError(
                    f"No staff member with id "
                    f"{options['staff_member_id']} "
                    f"for salon {options['salon_id']}.") from None

        start = _parse_date(options.get("start_date"), "start date")
        end = _parse_date(options.get("end_date"), "end date")
        if start is not None and end is not None and end < start:
            raise CommandError(
                "range end must not be before range start")
        try:
            text = export_attendance_records_csv(
                salon, staff_member=staff_member, start=start, end=end,
                event_type=options.get("event_type"))
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8",
                          newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: "
                    f"{exc}") from exc
        else:
            self.stdout.write(text, ending="")
