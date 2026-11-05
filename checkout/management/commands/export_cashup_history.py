"""Export a salon's cashup history as CSV or JSON.

Usage:
    python manage.py export_cashup_history --salon-id ID
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD
        [--format json|csv] [--output PATH]

Thin wrapper around the existing
:func:`checkout.cashup_history_export.export_cashup_history_csv`
and :func:`checkout.cashup_history_export.export_cashup_history`
services: the salon is resolved by id, the dates are parsed to
``datetime.date`` objects, and both are passed to the service
verbatim -- its output is written unchanged, to ``--output``
when given and to stdout otherwise. For ``--format csv`` (the
default) the service's CSV text is written exactly as before
and its own errors propagate unchanged (e.g. ``ValueError``
for a reversed range); for ``--format json`` the same dict
rows from
:func:`checkout.cashup_history_export.export_cashup_history`
are serialised as JSON, so the two formats can never disagree
-- one source of truth -- and service errors surface as
``CommandError``. An unknown format raises ``CommandError``.
Dates mean whole local days in the salon's timezone, inclusive
at both ends, exactly as the service defines them. Read-only.
Core stays provider-agnostic -- no payment-provider SDK, field,
or name appears here.
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from checkout.cashup_history_export import (
    export_cashup_history,
    export_cashup_history_csv,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's cashup history as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose cashup history to export.",
        )
        parser.add_argument(
            "--start-date", "--start", "--date-from", dest="start_date",
            type=_parse_date, required=True,
            help="First day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            type=_parse_date, required=True,
            help="Last day of the range, YYYY-MM-DD (inclusive).",
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
        if fmt == "json":
            try:
                rows = export_cashup_history(
                    salon, options["start_date"], options["end_date"]
                )
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
        else:
            text = export_cashup_history_csv(
                salon, options["start_date"], options["end_date"]
            )
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
