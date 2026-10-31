"""Export a salon's cashup detail as CSV.

Usage:
    python manage.py export_cashup_detail --salon-id ID
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD [--output PATH]

Thin wrapper around the existing
:func:`checkout.cashup_detail_export.export_cashup_detail_csv`
service: the salon is resolved by id, the dates are parsed to
``datetime.date`` objects, and both are passed to the service
verbatim -- its CSV text is written unchanged, to ``--output``
when given and to stdout otherwise. The service's own errors
propagate unchanged (e.g. ``ValueError`` for a reversed range).
Dates mean whole local days in the salon's timezone, inclusive
at both ends, exactly as the service defines them. Read-only.
Core stays provider-agnostic -- no payment-provider SDK, field,
or name appears here.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from checkout.cashup_detail_export import export_cashup_detail_csv
from saloncore.models import Salon


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's cashup detail as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose cashup detail to export.",
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
            "--output", default=None,
            help="Path to write the CSV to (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from exc
        text = export_cashup_detail_csv(
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
