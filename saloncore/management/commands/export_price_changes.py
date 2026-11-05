"""Export a salon's price-change audit history as CSV or JSON.

Usage:
    python manage.py export_price_changes --salon-id ID
        [--service-id ID]
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--format json|csv] [--output PATH]

Thin wrapper around :mod:`saloncore.price_change_export` -- that
service is the one source of truth for the price-change
export; this command only resolves the salon, parses the optional
dates to ``datetime.date`` objects, delegates to the service
verbatim, and writes what it returns (to ``--output`` when
given, otherwise to stdout). For ``--format csv`` (the default)
it writes :func:`saloncore.price_change_export.export_price_changes_csv`'s
CSV string, exactly as before; for ``--format json`` it
serialises the SAME dict rows from
:func:`saloncore.price_change_export.export_price_changes` as
JSON. Date semantics are exactly the service's:
start-inclusive, end covers the whole end day.

With ``--service-id`` the export is narrowed to that one
service's price changes: the service is resolved by id within
the salon (via its category's salon, the app's service scoping
convention; a service from another salon, or an unknown id, is
a ``CommandError``), and the resolved service is passed to the
service as its optional ``service`` argument. Without
``--service-id`` the command exports the whole salon, exactly
as before. ``--format`` composes with ``--service-id`` and the
date filters exactly as they do for CSV.
Backend only; read-only.
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon, Service
from saloncore.price_change_export import (
    export_price_changes,
    export_price_changes_csv,
)

_FORMATS = ("json", "csv")


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = (
        "Export a salon's price-change audit history as "
        "CSV (default) or JSON."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose price changes to export.",
        )
        parser.add_argument(
            "--service-id", type=int, default=None,
            help="Id of the service (in the salon) whose price "
                 "changes to export (default: all services).",
        )
        parser.add_argument(
            "--start-date", dest="start_date", type=_parse_date,
            default=None,
            help="First day of the range, YYYY-MM-DD (inclusive; "
                 "default: unbounded).",
        )
        parser.add_argument(
            "--end-date", dest="end_date", type=_parse_date,
            default=None,
            help="Last day of the range, YYYY-MM-DD (inclusive; "
                 "default: unbounded).",
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
        service = None
        if options.get("service_id") is not None:
            try:
                service = Service.objects.get(
                    pk=options["service_id"], category__salon=salon)
            except Service.DoesNotExist:
                raise CommandError(
                    f"No service with id {options['service_id']} "
                    f"for salon {options['salon_id']}."
                ) from None
        if fmt == "json":
            rows = export_price_changes(
                salon, start=options["start_date"],
                end=options["end_date"], service=service)
            text = json.dumps(rows, indent=2) + "\n"
        else:
            text = export_price_changes_csv(
                salon, start=options["start_date"],
                end=options["end_date"], service=service)
        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
