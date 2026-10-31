"""Export a salon's stocktake variance as CSV via the variance export service.

Usage:
    python manage.py export_variance --salon-id ID
        [--count PRODUCT_ID=COUNT ...] [--output PATH]

Backend only — no views, templates, or UI. This command is a thin
wrapper around
:func:`catalog.variance_export.export_stocktake_variance_csv`:
it resolves the salon by id, parses the optional counted quantities
into the ``counts`` mapping that service accepts, delegates to that
service verbatim, and writes the returned CSV to ``--output`` when
given, otherwise to stdout. It adds no fields, filtering, or
export logic of its own, so the command output and the service
output can never disagree — one source of truth. (The service also
offers a JSON-serializable list export built from the same lines;
this command uses its CSV variant, as in the ``export_valuation``
and ``export_low_stock`` commands, so no JSON rendering is needed.)

Counts semantics are the service's own: each ``--count`` names a
product of this salon by id with its counted quantity; a foreign
or unknown product raises the service's ``ValueError``, surfaced
here as ``CommandError``. With no ``--count`` at all the counts
mapping is empty, which the service exports as the header row alone.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.
"""
import argparse

from django.core.management.base import BaseCommand, CommandError

from catalog.variance_export import export_stocktake_variance_csv
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
    help = "Export a salon's stocktake variance as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose stocktake variance to export.",
        )
        parser.add_argument(
            "--count", dest="counts", action="append", default=None,
            type=_parse_count, metavar="PRODUCT_ID=COUNT",
            help="Counted quantity for one product of this salon; "
                 "repeat for each counted product (default: no "
                 "counts, which the service exports as the header "
                 "row alone).",
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
        counts = _coerce_counts(options.get("counts"))
        try:
            text = export_stocktake_variance_csv(salon, counts)
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
