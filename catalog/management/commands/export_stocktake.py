"""Export a salon's completed stocktake counts as JSON.

Usage:
    python manage.py export_stocktake --salon-id ID
        [--count PRODUCT_ID=COUNT ...] [--output PATH]

Backend only — no views, templates, or UI. This command is a thin
wrapper around :func:`catalog.stocktake_export.export_stocktake_counts`:
it resolves the salon by id, parses the optional counted quantities
into the ``counts`` mapping that service accepts, delegates to that
service verbatim, and writes the returned list of dicts — which the
service builds to be JSON-serializable — as JSON to ``--output``
when given, otherwise to stdout. It adds no fields, filtering, or
export logic of its own (JSON serialization of the service result,
as in the ``export_movement`` command, is the only rendering here),
so the command output and the service output can never disagree —
one source of truth.

Counts semantics are the service's own: each ``--count`` names a
product of this salon by id with its counted quantity; a foreign
or unknown product raises the service's ``ValueError``, surfaced
here as ``CommandError``. With no ``--count`` at all the counts
mapping is empty, which the service exports as an empty list.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.
"""
import argparse
import json

from django.core.management.base import BaseCommand, CommandError

from catalog.stocktake_export import export_stocktake_counts
from saloncore.models import Salon


def _parse_count(value):
    try:
        key, _, quantity = str(value).partition("=")
        return int(key), int(quantity)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid count {value!r}; expected PRODUCT_ID=COUNT."
        ) from exc


def _coerce_counts(raw):
    """Normalise the counts option to the service's mapping.

    ``None`` means no counts were given (the service's empty case);
    a mapping passes through verbatim (programmatic callers); an
    iterable of ``PRODUCT_ID=COUNT`` strings or ``(id, count)``
    pairs, as produced by the argument parser, becomes a dict.
    """
    if raw is None:
        return {}
    if hasattr(raw, "items"):
        return raw
    counts = {}
    for entry in raw:
        if isinstance(entry, str):
            try:
                entry = _parse_count(entry)
            except argparse.ArgumentTypeError as exc:
                raise CommandError(str(exc)) from exc
        key, quantity = entry
        if key in counts:
            raise CommandError(f"Duplicate count for product {key}.")
        counts[key] = quantity
    return counts


class Command(BaseCommand):
    help = "Export a salon's completed stocktake counts as JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose stocktake counts to export.",
        )
        parser.add_argument(
            "--count", dest="counts", action="append", default=None,
            type=_parse_count, metavar="PRODUCT_ID=COUNT",
            help="Counted quantity for one product of this salon; "
                 "repeat for each counted product (default: no "
                 "counts, which the service exports as an empty list).",
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
        counts = _coerce_counts(options.get("counts"))
        try:
            records = export_stocktake_counts(salon, counts)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        text = json.dumps(records, indent=2) + "\n"
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
