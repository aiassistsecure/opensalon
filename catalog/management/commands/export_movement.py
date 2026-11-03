"""Export a salon's stock movements as JSON or CSV.

Usage:
    python manage.py export_movement --salon-id ID
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--format json|csv] [--output PATH]

Backend only — no views, templates, or UI. This command is a thin
wrapper around :mod:`catalog.movement_export`: it resolves the
salon by id, parses the optional dates, and delegates verbatim —
to :func:`~catalog.movement_export.export_movement_export` for
``--format json`` (the default; the returned dict, which the
service builds to be JSON-serializable, is written as JSON), or
to :func:`~catalog.movement_export.export_movements_csv` for
``--format csv`` (that service's CSV string, built from the same
movement rows, is written as-is). Output goes to ``--output``
when given, otherwise to stdout. The command adds no fields,
filtering, or export logic of its own, so the command output and
the service output can never disagree — one source of truth.

The CSV rendering carries the movement rows only, with
:data:`~catalog.movement_export.MOVEMENT_FIELDNAMES` as its
header; the per-product totals rollup stays in the JSON export.

Range semantics are the service's own: start-inclusive,
end-exclusive after normalisation, so a date end covers the whole
end day; either bound may be omitted (unbounded).

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from catalog.movement_export import (
    export_movement_export,
    export_movements_csv,
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
    help = "Export a salon's stock movements (with totals) as JSON or CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose stock movements to export.",
        )
        parser.add_argument(
            "--start-date", "--start", dest="start_date",
            type=_parse_date, default=None,
            help="First day of the range, YYYY-MM-DD (inclusive; "
                 "default: unbounded).",
        )
        parser.add_argument(
            "--end-date", "--end", dest="end_date",
            type=_parse_date, default=None,
            help="Last day of the range, YYYY-MM-DD (the whole day "
                 "is included; default: unbounded).",
        )
        parser.add_argument(
            "--format", dest="format", default="json", choices=_FORMATS,
            help="Export format: json (default) or csv.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the export file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        fmt = options.get("format") or "json"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        try:
            if fmt == "csv":
                text = export_movements_csv(
                    salon, start=options["start_date"],
                    end=options["end_date"])
            else:
                data = export_movement_export(
                    salon, start=options["start_date"],
                    end=options["end_date"])
                text = json.dumps(data, indent=2) + "\n"
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
