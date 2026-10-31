"""Export a salon's stock adjustments as CSV via the adjust export service.

Usage:
    python manage.py export_adjust --salon-id ID
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--output PATH]

Backend only — no views, templates, or UI. This command is a thin
wrapper around
:func:`catalog.adjust_export.export_stock_adjustments_csv`:
it resolves the salon by id, parses the optional dates, delegates
to that service verbatim (with the same optional ``start`` /
``end``), and writes the returned CSV to ``--output`` when given,
otherwise to stdout. It adds no fields, filtering, or export logic
of its own, so the command output and the service output can
never disagree — one source of truth. (The service also offers a
JSON-serializable list export built from the same records; this
command uses its CSV variant, as in the ``export_stock_history``
command, so no JSON rendering is needed.)

Range semantics are the service's own: start-inclusive,
end-exclusive after normalisation, so a date end covers the whole
end day; either bound may be omitted (unbounded).

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from catalog.adjust_export import export_stock_adjustments_csv
from saloncore.models import Salon


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's stock adjustments as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose stock adjustments to export.",
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
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        try:
            text = export_stock_adjustments_csv(
                salon, start=options["start_date"],
                end=options["end_date"])
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
