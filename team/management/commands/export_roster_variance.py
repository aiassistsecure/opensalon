"""Export one salon's rostered-vs-actual variance as CSV or JSON.

Usage:
    python manage.py export_roster_variance --salon-id ID
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD
        [--format json|csv] [--output PATH]

Thin wrapper around
:mod:`team.variance_export`: the salon is resolved by id,
dates are parsed, and all three are passed to the service
verbatim. For ``--format csv`` (the default) it delegates
verbatim to
:func:`team.variance_export.export_roster_variance_csv`, so
CSV output is byte-identical to before; for ``--format json``
it serialises the SAME dict rows from
:func:`team.variance_export.export_roster_variance` as JSON
via ``DjangoJSONEncoder``, so the two formats can never
disagree -- one source of truth. An unknown salon, a missing
or unparseable date, a reversed range, or an unknown
``--format`` raises ``CommandError`` (argparse ``choices``
reject it on the CLI; the explicit check covers
``call_command`` kwargs). Backend only. Read-only.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from saloncore.models import Salon
from team.variance_export import (
    export_roster_variance,
    export_roster_variance_csv,
)

_FORMATS = ("json", "csv")


def _parse_date(value, label):
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if value in (None, ""):
        raise CommandError(f"Missing {label}; expected YYYY-MM-DD.")
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD.") from exc


class Command(BaseCommand):
    help = "Export one salon's rostered-vs-actual variance as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", required=True, type=int,
                            help="Id of the salon to export.")
        parser.add_argument("--start-date", dest="start_date", required=True,
                            help="First day, YYYY-MM-DD (inclusive).")
        parser.add_argument("--end-date", dest="end_date", required=True,
                            help="Last day, YYYY-MM-DD (inclusive).")
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.")
        parser.add_argument("--output", default=None,
                            help="Export file to write (default: stdout).")

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None
        start = _parse_date(options.get("start_date"), "start date")
        end = _parse_date(options.get("end_date"), "end date")
        try:
            if fmt == "json":
                rows = export_roster_variance(salon, start, end)
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_roster_variance_csv(salon, start, end)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if options.get("output"):
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
