"""Reconcile a salon's stock to a physical stocktake count.

Usage:
    python manage.py reconcile_stocktake --salon-id ID
        --reference REFERENCE [--count PRODUCT_ID=COUNT ...]

Backend only — no views, templates, or UI. This command is a thin
wrapper around :func:`catalog.stocktake.reconcile_stocktake`: it
resolves the salon by id, parses the counted quantities into the
``counts`` mapping that service accepts, delegates to that service
verbatim, and prints the returned ``StocktakeResult`` as JSON to
stdout. It adds no reconciliation, movement, or idempotency logic
of its own — movements remain the one source of truth and the
service alone decides which reconciling movements to record — so
the printed result and the recorded movements can never disagree.

Counts and reference semantics are the service's own: each
``--count`` names a product of this salon by id with its counted
quantity, the reference is required and is the unit of
idempotency (re-running with an already-applied reference records
nothing new and prints ``already_applied`` as true), and an empty
counts mapping, a blank reference, a negative or non-integer
count, or a foreign or unknown product raises the service's
``ValueError``, surfaced here as ``CommandError``.
"""
import argparse
import json

from django.core.management.base import BaseCommand, CommandError

from catalog.stocktake import reconcile_stocktake
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

    ``None`` means no counts were given (the service's empty case,
    which it rejects); a mapping passes through verbatim
    (programmatic callers, whose keys may be products, ids, or
    barcode/SKU codes exactly as the service accepts); an iterable
    of ``PRODUCT_ID=COUNT`` strings or ``(id, count)`` pairs, as
    produced by the argument parser, becomes a dict.
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


def _result_dict(result):
    """Render a ``StocktakeResult`` as a JSON-serializable dict."""
    return {
        "reference": result.reference,
        "already_applied": result.already_applied,
        "has_variance": result.has_variance,
        "variances": [
            {
                "product_id": variance.product.pk,
                "product_name": variance.product.name,
                "expected_stock": variance.expected_stock,
                "counted_stock": variance.counted_stock,
                "variance": variance.variance,
                "movement_id": (
                    variance.movement.pk if variance.movement else None
                ),
            }
            for variance in result.variances
        ],
    }


class Command(BaseCommand):
    help = "Reconcile a salon's stock to a stocktake count."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose stock to reconcile.",
        )
        parser.add_argument(
            "--reference", default=None,
            help="Stocktake reference (required by the service); "
                 "re-running with the same reference records "
                 "nothing new.",
        )
        parser.add_argument(
            "--count", dest="counts", action="append", default=None,
            type=_parse_count, metavar="PRODUCT_ID=COUNT",
            help="Counted quantity for one product of this salon; "
                 "repeat for each counted product.",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        counts = _coerce_counts(options.get("counts"))
        try:
            result = reconcile_stocktake(
                salon, counts, options.get("reference"))
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        text = json.dumps(_result_dict(result), indent=2) + "\n"
        self.stdout.write(text, ending="")
