"""Stock movement export service for the catalog.

Backend only — no views, templates, or UI. Read-only: this service
never creates, edits, or deletes a stock movement; the movement
ledger stays append-only and is only read here.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's ``StockMovement`` ledger
entries for a date range as a plain, JSON-serializable list of
dicts (:func:`export_movements`), plus a per-product totals rollup
for the same range (:func:`movement_totals`). Both are built from
the same filtered queryset, so the rollup can never disagree with
the rows — one source of truth.

Fields per movement: ``id``, ``product_id``, ``product_name``,
``sku``, ``barcode``, ``quantity_delta``, ``kind`` (the movement
type, from ``StockMovement.Kind``), ``note`` (the free-text reason
field on the model), and ``created_at``. ``created_at`` is an
ISO-8601 string because a ``datetime`` is not JSON-serializable.

Fields per totals row: ``product_id``, ``product_name``, ``sku``,
``barcode``, ``movement_count``, ``net_delta`` (the sum of
``quantity_delta`` over the range), and ``by_kind`` (a dict of
per-kind delta sums; only kinds present in the range appear).
Only products with at least one movement in the range appear in
the rollup. Negative sums are reported as they stand, never
clamped — the ledger is reported as it is.

Range semantics: ``start`` / ``end`` may each be a ``date``, a
``datetime``, or ``None`` (unbounded). The range is start-inclusive
and end-exclusive after normalisation: a ``date`` start means the
start of that day, and a ``date`` end means the start of the
*following* day, so passing two dates includes the whole end day.
A ``datetime`` is used as given (naive datetimes are interpreted
in the current time zone). Ordering of movement rows is
deterministic: by ``created_at``, then id (the model's own
ordering). Totals rows are ordered by product name, then id.

The CSV rendering (:func:`export_movements_csv`) is built from
that same :func:`export_movements` list, so the two formats can
never disagree — one source of truth. It renders the movement
rows only (the totals rollup stays in the JSON-shaped combined
export); it adds no fields, filtering, or computation of its own.

Every export here also takes one optional per-product filter,
``product`` (default ``None``): a saved
:class:`~catalog.models.Product` or its integer id, resolved
within the salon exactly as
:func:`catalog.history.stock_history` resolves it — an unknown
id, an unsaved instance, or a product of another salon raises
``ValueError`` rather than leaking. With a product, only that
product's movements (still inside the date range) are exported,
and the totals rollup covers that product alone, so the two
halves of the combined export still reconcile. With ``None``
(the default), the output is the previous salon-wide export,
unchanged.

Kind filter: every export here also takes one optional
``kind`` (default ``None`` = no kind filter, output identical
to the unfiltered export). With a kind, only movements whose
stored ``kind`` exactly matches it are exported —
``kind=str(kind)``, so a ``StockMovement.Kind`` member works,
with no case folding — mirroring the sibling categorical
filters. The kind filter composes (AND) with the product and
the range, and because the rows and the totals rollup are
built from the same filtered queryset, a kind-filtered rollup
still reconciles with the kind-filtered rows.
"""
import csv
import io
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from catalog.history import _resolve_product
from catalog.models import StockMovement

__all__ = [
    "MOVEMENT_FIELDNAMES",
    "TOTAL_FIELDNAMES",
    "export_movements",
    "export_movements_csv",
    "movements_csv",
    "movement_totals",
    "export_movement_export",
    "movement_export",
]

#: Key order for each exported movement dict.
MOVEMENT_FIELDNAMES = [
    "id",
    "product_id",
    "product_name",
    "sku",
    "barcode",
    "quantity_delta",
    "kind",
    "note",
    "created_at",
]

#: Key order for each per-product totals dict (``by_kind`` holds
#: a nested dict and is therefore listed last).
TOTAL_FIELDNAMES = [
    "product_id",
    "product_name",
    "sku",
    "barcode",
    "movement_count",
    "net_delta",
    "by_kind",
]


def _bound(value, *, is_end):
    """Normalise a range bound to an aware datetime or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        bound = value
    elif isinstance(value, date):
        bound = datetime.combine(value, time.min)
        if is_end:
            bound += timedelta(days=1)
    else:
        raise ValueError("range bounds must be a date, datetime, or None")
    if timezone.is_naive(bound):
        bound = timezone.make_aware(bound, timezone.get_current_timezone())
    return bound


def _movements_in_range(salon, start, end, product=None, kind=None):
    salon_id = getattr(salon, "pk", salon)
    queryset = (
        StockMovement.objects.filter(product__salon_id=salon_id)
        .select_related("product")
        .order_by("created_at", "id")
    )
    if product is not None:
        queryset = queryset.filter(product=_resolve_product(salon, product))
    if kind is not None:
        queryset = queryset.filter(kind=str(kind))
    start_bound = _bound(start, is_end=False)
    end_bound = _bound(end, is_end=True)
    if start_bound is not None:
        queryset = queryset.filter(created_at__gte=start_bound)
    if end_bound is not None:
        queryset = queryset.filter(created_at__lt=end_bound)
    return queryset


def _record(movement):
    product = movement.product
    return {
        "id": movement.pk,
        "product_id": product.pk,
        "product_name": product.name,
        "sku": product.sku,
        "barcode": product.barcode,
        "quantity_delta": int(movement.quantity_delta),
        "kind": movement.kind,
        "note": movement.note,
        "created_at": movement.created_at.isoformat(),
    }


def export_movements(salon, start=None, end=None, *, product=None,
                     kind=None):
    """Return ``salon``'s movements in the range as a list of dicts.

    Each entry is a dict with exactly :data:`MOVEMENT_FIELDNAMES`
    keys (see the module docstring for range semantics). Only
    ``salon``'s movements are included. Ordered by ``created_at``,
    then id. A range with no movements exports as ``[]``.

    The optional ``product`` (a saved Product or its id, resolved
    within ``salon``; see the module docstring) restricts the
    export to that one product's movements, still inside the
    range. Default ``None`` is the salon-wide export, unchanged.
    The optional ``kind`` filters by exact stored kind value
    (AND with the product and the range); ``None`` (the default)
    applies no kind filter. Records nothing.
    """
    return [
        _record(m)
        for m in _movements_in_range(
            salon, start, end, product=product, kind=kind)
    ]


def export_movements_csv(salon, start=None, end=None, *, product=None,
                         kind=None):
    """Return ``salon``'s movements in the range as a CSV string.

    The header row is :data:`MOVEMENT_FIELDNAMES` and every data
    row comes from :func:`export_movements` with the same
    arguments (including the optional ``product`` filter and
    the optional ``kind`` filter), so the CSV and list exports
    always agree. A range with no movements (or none of the
    kind) exports as the header row alone. Lines end
    with ``"\\n"``. Records nothing.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=MOVEMENT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_movements(
            salon, start=start, end=end, product=product, kind=kind):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
movements_csv = export_movements_csv


def movement_totals(salon, start=None, end=None, *, product=None,
                    kind=None):
    """Return per-product totals for ``salon``'s movements in range.

    Each entry is a dict with exactly :data:`TOTAL_FIELDNAMES`
    keys: the product's identity fields, how many movements it had
    in the range, the net ``quantity_delta`` sum, and a ``by_kind``
    dict of per-kind delta sums. Only products with movements in
    the range appear. Ordered by product name, then id. A range
    with no movements returns ``[]``. The optional ``product``
    and ``kind`` filters are :func:`export_movements`' own, so a
    filtered rollup still reconciles with the filtered rows.
    Records nothing.
    """
    totals = {}
    for movement in _movements_in_range(
            salon, start, end, product=product, kind=kind):
        product = movement.product
        row = totals.get(product.pk)
        if row is None:
            row = {
                "product_id": product.pk,
                "product_name": product.name,
                "sku": product.sku,
                "barcode": product.barcode,
                "movement_count": 0,
                "net_delta": 0,
                "by_kind": {},
            }
            totals[product.pk] = row
        delta = int(movement.quantity_delta)
        row["movement_count"] += 1
        row["net_delta"] += delta
        row["by_kind"][movement.kind] = row["by_kind"].get(movement.kind, 0) + delta
    return sorted(
        totals.values(), key=lambda r: (r["product_name"], r["product_id"])
    )


def export_movement_export(salon, start=None, end=None, *, product=None,
                           kind=None):
    """Return ``{"movements": [...], "totals": [...]}`` for the range.

    Both halves come from the same range arguments (and the same
    optional ``product`` and ``kind`` filters), so the totals
    always reconcile with the exported rows.
    """
    return {
        "movements": export_movements(
            salon, start=start, end=end, product=product, kind=kind),
        "totals": movement_totals(
            salon, start=start, end=end, product=product, kind=kind),
    }


#: Aliases, mirroring the naming convenience in sibling services.
movement_export = export_movement_export
