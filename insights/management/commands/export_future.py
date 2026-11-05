"""Export a salon's future appointments value report as CSV or JSON.

Usage:
    python manage.py export_future --salon-id ID
        [--as-of ISO-8601-DATETIME] [--format json|csv]
        [--output PATH]

Thin wrapper around the existing
:mod:`insights.future_export` service: the salon is resolved
by id, ``--as-of`` is parsed to a timezone-aware
``datetime.datetime``, and both are passed to the service
verbatim — its output is written unchanged, to ``--output``
when given and to stdout otherwise. For ``--format csv`` (the
default) it writes
:func:`insights.future_export.export_future_appointments_value_csv`'s
CSV string, exactly as before; for ``--format json`` it
serialises the SAME dict rows from
:func:`insights.future_export.export_future_appointments_value`
as JSON. Money values are already strings in those rows, so
JSON carries them as strings, never floats. ``--as-of``
defaults to ``None``, exactly as the service defines it (the
service's own "now"). A date-only ``--as-of`` means the start
of that day in the salon's timezone; a naive datetime is read
in the salon's timezone. This command adds no export logic of
its own, so command and service output can never disagree —
one source of truth.

An unknown salon, an unparseable ``--as-of``, an unknown
format, or a service error raises ``CommandError``. Read-only.
"""
import datetime
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management.base import BaseCommand, CommandError

from insights.future_export import (
    export_future_appointments_value,
    export_future_appointments_value_csv,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _salon_tz(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def _parse_as_of(value, salon):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value
    tz = _salon_tz(salon)
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(
            value, datetime.time.min, tzinfo=tz)
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        try:
            day = datetime.date.fromisoformat(text)
        except ValueError as exc:
            raise CommandError(
                f"Invalid as-of {value!r}; expected an ISO-8601 "
                "datetime."
            ) from exc
        return datetime.datetime.combine(
            day, datetime.time.min, tzinfo=tz)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


class Command(BaseCommand):
    help = "Export a salon's future appointments value report as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose future appointments value "
                 "report to export.",
        )
        parser.add_argument(
            "--as-of", dest="as_of", default=None, required=False,
            help="Reference instant, ISO-8601 datetime "
                 "(default: the service's own default).",
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
        as_of = _parse_as_of(options.get("as_of"), salon)
        try:
            if fmt == "json":
                rows = export_future_appointments_value(salon, as_of)
                text = json.dumps(rows, indent=2) + "\n"
            else:
                text = export_future_appointments_value_csv(salon, as_of)
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
