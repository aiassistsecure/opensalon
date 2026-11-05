"""Export a salon's due reminders as CSV or JSON.

Usage:
    python manage.py export_due_reminders --salon-id ID
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD
        [--channel CHANNEL] [--format json|csv] [--output PATH]

Thin wrapper around
:func:`messaging.due_export.export_due_reminders_csv` and
its dict twin
:func:`messaging.due_export.export_due_reminders`:
the salon is resolved by id and both bounds are passed to the
service as ``(salon, start, end)`` -- for ``--format csv``
(the default) its CSV text is written unchanged, exactly as
before; for ``--format json`` the same dict rows are
serialised as JSON. Output goes to ``--output`` when given
and to stdout otherwise. This command adds no export logic
of its own, so command and service output can never
disagree -- one source of truth. In particular the service's
per-channel opt-in behaviour carries through exactly; this
command never re-checks opt-ins.

The service's window bounds are datetimes, inclusive at both
ends. ``datetime`` bounds (passed programmatically or as an
ISO datetime string) are passed verbatim. Plain dates mean
whole local days in the salon's timezone, inclusive at both
ends: a start date becomes the start of that day and an end
date the end of that day in that timezone.

Invalid input -- an unknown salon, an unparseable date, a
reversed range, or an unknown ``--format`` -- raises
``CommandError``. Read-only. Core stays provider-agnostic --
no provider SDK, field, or name appears here.
"""
import datetime
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management.base import BaseCommand, CommandError

from messaging.due_export import (
    export_due_reminders,
    export_due_reminders_csv,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _tz_for(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def _parse_bound(value, label, salon, is_end):
    if isinstance(value, datetime.datetime):
        return value
    tz = _tz_for(salon)
    if isinstance(value, datetime.date):
        day = value
    elif isinstance(value, str) and (
            "T" in value or " " in value.strip()):
        try:
            parsed = datetime.datetime.fromisoformat(value)
        except ValueError as exc:
            raise CommandError(
                f"Invalid {label} {value!r}; expected YYYY-MM-DD."
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed
    else:
        try:
            day = datetime.date.fromisoformat(str(value))
        except ValueError as exc:
            raise CommandError(
                f"Invalid {label} {value!r}; expected YYYY-MM-DD."
            ) from exc
    bound_time = datetime.time.max if is_end else datetime.time.min
    return datetime.datetime.combine(day, bound_time, tzinfo=tz)


class Command(BaseCommand):
    help = "Export a salon's due reminders as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose due reminders to export.",
        )
        parser.add_argument(
            "--start-date", dest="start_date", required=True,
            help="First day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--end-date", dest="end_date", required=True,
            help="Last day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--channel", dest="channel", default=None,
            help="Reminder channel value to filter by.",
        )
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path to write the export to (default: stdout).",
        )

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from exc
        start = _parse_bound(
            options["start_date"], "start date", salon, is_end=False)
        end = _parse_bound(
            options["end_date"], "end date", salon, is_end=True)
        if end < start:
            raise CommandError(
                f"End date {options['end_date']!r} is before start "
                f"date {options['start_date']!r}."
            )
        try:
            if fmt == "json":
                rows = export_due_reminders(
                    salon, start, end, channel=options.get("channel"))
                text = json.dumps(rows, indent=2) + "\n"
            else:
                text = export_due_reminders_csv(
                    salon, start, end, channel=options.get("channel"))
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8",
                          newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
