"""Export a salon's client summaries as CSV or JSON.

Usage:
    python manage.py export_summary --salon-id ID
        [--now ISO-DATETIME] [--format json|csv] [--output PATH]

Thin wrapper around ``clients.summary_export`` -- that
service is the one source of truth for the client summary export
shape; this command only resolves the salon, delegates verbatim,
and routes what it returns to the ``--output`` file when given
or to stdout otherwise. It never reimplements serialization or
querying. ``--now`` is passed through to the service unchanged,
with the service's own default when omitted.

For ``--format csv`` (the default) it writes
:func:`clients.summary_export.export_client_summaries_csv`'s
CSV string, exactly as before (byte-identical); for
``--format json`` it serialises the SAME dict rows from
:func:`clients.summary_export.export_client_summaries` as JSON.
``--now`` composes with ``--format`` exactly as it does for CSV.

Note: the global command name ``export_summary`` is also owned
by the checkout app's command; callers pinning this app's command
should load it explicitly via
``load_command_class("clients", "export_summary")``, exactly as
the checkout tests pin theirs.

Backend only: no views, templates, or UI. No provider concepts.
"""
import datetime
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management.base import BaseCommand, CommandError

from clients.summary_export import (
    export_client_summaries,
    export_client_summaries_csv,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _tz_for(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def _parse_now(value, salon):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value
    tz = _tz_for(salon)
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(
            value, datetime.time.min, tzinfo=tz)
    text = str(value).strip()
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        try:
            day = datetime.date.fromisoformat(text)
        except ValueError as exc:
            raise CommandError(
                f"Invalid now {value!r}; expected an ISO datetime."
            ) from exc
        return datetime.datetime.combine(
            day, datetime.time.min, tzinfo=tz)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


class Command(BaseCommand):
    help = "Export a salon's client summaries as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose client summaries to export.",
        )
        parser.add_argument(
            "--now", dest="now", default=None,
            help="Reference instant, ISO datetime "
                 "(default: the service's own default).",
        )
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the export file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from None

        now = _parse_now(options.get("now"), salon)

        try:
            if fmt == "json":
                rows = export_client_summaries(salon, now=now)
                text = json.dumps(rows, indent=2) + "\n"
            else:
                text = export_client_summaries_csv(salon, now=now)
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(
                f"Client summary export failed: {exc}"
            ) from exc

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
