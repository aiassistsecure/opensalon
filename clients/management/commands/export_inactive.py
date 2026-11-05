"""Export a salon's inactive clients as CSV or JSON.

Usage:
    python manage.py export_inactive --salon-id ID
        [--days N] [--now ISO-DATETIME] [--threshold-days N]
        [--format json|csv] [--output PATH]

Thin wrapper around ``clients.inactive_export.export_inactive_csv``
and its dict twin ``clients.inactive_export.export_inactive_clients``
-- those services are the one source of truth for the inactive
export shape; this command only resolves the salon, delegates
verbatim, and routes the text it returns to the ``--output``
file when given or to stdout otherwise. For ``--format csv``
(the default) the CSV text is written unchanged, exactly as
before; for ``--format json`` the same arguments are passed to
the dict service and its rows are serialised as JSON, so the
two formats can never disagree. It never reimplements querying.
``--days``, ``--now`` and ``--threshold-days`` are
passed through to the service unchanged, with the service's own
defaults when omitted (``--days`` defaults to
:data:`clients.inactive.DEFAULT_INACTIVE_DAYS`, exactly as
before this command exposed the arguments).

Invalid input -- an unknown salon, an unknown ``--format``, or
a service error -- raises ``CommandError``, as does an
unwritable ``--output`` path.

Backend only: no views, templates, or UI. No provider concepts.
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from clients.inactive import DEFAULT_INACTIVE_DAYS
from clients.inactive_export import (
    export_inactive_clients,
    export_inactive_csv,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _parse_datetime(value):
    try:
        return _datetime_from_string(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid datetime {value!r}; expected ISO-8601."
        ) from exc


def _datetime_from_string(value):
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(text)


def _coerce_now(value):
    if value is None or isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(
            value, datetime.time.min, tzinfo=datetime.timezone.utc)
    try:
        return _datetime_from_string(value)
    except ValueError as exc:
        raise CommandError(
            f"Invalid now {value!r}; expected ISO-8601 datetime."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's inactive clients as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose inactive clients to export.",
        )
        parser.add_argument(
            "--days", dest="days", type=int,
            default=DEFAULT_INACTIVE_DAYS,
            help="Inactivity window in days "
                 "(default: the service's own default).",
        )
        parser.add_argument(
            "--now", dest="now", type=_parse_datetime, default=None,
            help="Reference instant, ISO datetime "
                 "(default: the service's own default).",
        )
        parser.add_argument(
            "--threshold-days", dest="threshold_days", type=int,
            default=None,
            help="Inactivity window in days; when given, takes "
                 "precedence over --days, exactly as in the service.",
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

        now = _coerce_now(options.get("now"))
        days = options.get("days")
        if days is None:
            days = DEFAULT_INACTIVE_DAYS

        try:
            if fmt == "json":
                rows = export_inactive_clients(
                    salon, days=days, now=now,
                    threshold_days=options.get("threshold_days"),
                )
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_inactive_csv(
                    salon, days=days, now=now,
                    threshold_days=options.get("threshold_days"),
                )
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
