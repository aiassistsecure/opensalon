"""Export one salon's staff notifications as CSV or JSON.

Usage:
    python manage.py export_staff_notifications --salon-id ID
        [--staff-member-id ID] [--kind KIND]
        [--seen-only | --unseen-only]
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--format json|csv]
        [--output PATH]

Thin wrapper around the existing
:mod:`team.notification_export` service: the salon is resolved
by id and passed to the service verbatim. For ``--format csv``
(the default) it delegates verbatim to
:func:`team.notification_export.export_staff_notifications_csv`,
so CSV output is byte-identical to before; for
``--format json`` it serialises the SAME dict rows from
:func:`team.notification_export.export_staff_notifications` as
JSON via ``DjangoJSONEncoder``, so the two formats can never
disagree -- one source of truth. The text is written to
``--output`` when given and to stdout otherwise. An unknown
``--format`` raises ``CommandError`` (argparse ``choices``
reject it on the CLI; the explicit check covers
``call_command`` kwargs).

With ``--staff-member-id`` the export is narrowed to that one
staff member's notifications: the staff member is resolved
by id within the salon (a staff member from another salon, or
an unknown id, is a ``CommandError``), and the resolved staff
member is passed to the service as its optional
``staff_member`` argument. Without ``--staff-member-id`` the
command exports the whole salon, exactly as before.

With ``--kind`` the export is narrowed to notifications whose
stored ``kind`` exactly equals it: the value is passed to the
service as its optional ``kind`` argument. Without ``--kind``
the command exports every kind, exactly as before. ``--kind``
composes with ``--staff-member-id`` (both must match).

With ``--seen-only`` only seen notifications (``seen_at`` not
null) are exported; with ``--unseen-only`` only unseen ones.
The flags conflict if both are given (``CommandError``).
Without either, seen state is unfiltered, exactly as before.
They compose with ``--staff-member-id`` and ``--kind``.

With ``--start-date`` / ``--end-date`` (spelled exactly as
``export_attendance_records`` spells them; ``--date-from`` /
``--date-to`` accepted as aliases) the export is narrowed to
notifications whose ``created_at`` falls in that window: the
dates are parsed to ``datetime.date`` objects and passed to
the service as its optional ``start`` / ``end`` arguments,
so a date start means the start of that day and a date end
includes the whole end day. Each bound is optional; without
either, the command exports every notification, exactly as
before. The window composes with ``--staff-member-id``,
``--kind``, and the seen flags (all must match).

An unknown salon, an unparseable date, or a reversed range
raises ``CommandError``. Backend only -- no views,
templates, or UI. Read-only.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from saloncore.models import Salon
from team.models import StaffMember
from team.notification_export import (
    export_staff_notifications,
    export_staff_notifications_csv,
)

_FORMATS = ("json", "csv")


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
    help = "Export one salon's staff notifications as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose staff notifications to export.")
        parser.add_argument(
            "--staff-member-id", type=int, default=None,
            help="ID of the staff member (in the salon) whose "
                 "notifications to export "
                 "(default: all staff members).")
        parser.add_argument(
            "--kind", default=None,
            help="Notification kind to export "
                 "(default: all kinds).")
        parser.add_argument(
            "--seen-only", action="store_true",
            help="Only seen notifications.")
        parser.add_argument(
            "--unseen-only", action="store_true",
            help="Only unseen notifications.")
        parser.add_argument(
            "--start-date", "--date-from", "--from-date",
            dest="start_date", default=None,
            help="First day of the range on created_at, "
                 "YYYY-MM-DD (inclusive; default: unbounded).")
        parser.add_argument(
            "--end-date", "--date-to", "--to-date",
            dest="end_date", default=None,
            help="Last day of the range on created_at, "
                 "YYYY-MM-DD (inclusive; default: unbounded).")
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.")
        parser.add_argument(
            "--output", default=None,
            help="Path of the export file to write (default: stdout).")

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        if options.get("seen_only") and options.get("unseen_only"):
            raise CommandError(
                "--seen-only and --unseen-only conflict.")
        seen = (
            True if options.get("seen_only")
            else False if options.get("unseen_only") else None)
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
            if fmt == "json":
                rows = export_staff_notifications(
                    salon, staff_member=staff_member,
                    kind=options.get("kind"), seen=seen,
                    start=start, end=end)
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_staff_notifications_csv(
                    salon, staff_member=staff_member,
                    kind=options.get("kind"), seen=seen,
                    start=start, end=end)
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
