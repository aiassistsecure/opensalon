"""Export a salon's stock movements as JSON via the movement export service.

Usage:
    python manage.py export_movement --salon-id ID
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--output PATH]

Backend only — no views, templates, or UI. This command is a thin
wrapper around :func:`catalog.movement_export.export_movement_export`:
it resolves the salon by id, parses the optional dates, delegates
to that service verbatim (with the same optional ``start`` /
``end``), and writes the returned dict — which the service builds
to be JSON-serializable — as JSON to ``--output`` when given,
otherwise to stdout. It adds no fields, filtering, or export logic
of its own (the service has no CSV variant; JSON serialization of
its result, as in the ``export_clients`` command, is the only
rendering here), so the command output and the service output can
never disagree — one source of truth.

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

from catalog.movement_export import export_movement_export
from saloncore.models import Salon


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's stock movements (with totals) as JSON."

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
            "--output", default=None,
            help="Path of the JSON file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        try:
            data = export_movement_export(
                salon, start=options["start_date"],
                end=options["end_date"])
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        text = json.dumps(data, indent=2) + "\n"
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
